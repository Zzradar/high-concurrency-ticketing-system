import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase14_model import load_targets
from run_phase14 import build_spec, check_startup
from phase14_startup import background_initialization
from phase14_evidence import verdict

class StartupTests(unittest.TestCase):
    def test_clock_transport_excludes_cli_startup_and_always_closes(self):
        from unittest.mock import Mock,patch
        from phase14_sampling import postgres_clock_sample
        connection=Mock(pid=123);env=Mock(t=load_targets(smoke=True))
        connection.sql.return_value=json.dumps({'time':10.002})
        with patch('phase14_pg_stream.ActivityConnection',return_value=connection),patch('phase14_sampling.time.time',side_effect=[10,10.004]):
            value=postgres_clock_sample(env)
        self.assertAlmostEqual(value['clockSkewMs'],0);self.assertAlmostEqual(value['clockUncertaintyMs'],2)
        self.assertTrue(value['clockConnectionClosed']);connection.close.assert_called_once()
        connection.reset_mock();connection.sql.side_effect=RuntimeError('query failed')
        with patch('phase14_pg_stream.ActivityConnection',return_value=connection):
            with self.assertRaises(RuntimeError):postgres_clock_sample(env)
        connection.close.assert_called_once()

    def test_only_authorized_configuration_changes(self):
        old=json.loads(subprocess.check_output(['git','show','84a0acd:performance/baseline/phase14-targets.json'],cwd=ROOT))
        current=json.loads((ROOT/'performance/baseline/phase14-targets.json').read_text())
        self.assertEqual(current.pop('version'),3);old.pop('version')
        startup=current.pop('pageStartup');self.assertEqual(sum(startup['stepCounts'].values()),10)
        self.assertEqual(current,old)

    def test_all_modes_exact_plan_and_slice_conservation(self):
        for smoke in (False,True):
            t=load_targets(smoke=smoke);n=t['burst']['users']
            for case in ('U1','U2','J1','S1','O1','H1','L1','L2'):
                spec=build_spec(t,case,'test',passed_u1=[n],passed_u2=[n])
                p=spec['startupPlan'];self.assertEqual(p['users'],n if case in ('U1','U2','J1','S1') else 0)
                self.assertEqual(p['requests'],p['users']*10)
                summary={'counts':[{'metric':metric,'tags':['main',step,'business_success'],'count':count}
                    for step,count in {'startup':p['users'],**p['steps']}.items() for metric in ('phase14_started','phase14_results')],'errors':[]}
                check_startup(summary,p);self.assertEqual(summary['errors'],[])
                if p['users']:
                    summary['counts'][0]['count']-=1;check_startup(summary,p);self.assertTrue(summary['errors'])
                if case.startswith('L'):
                    ranges=[]
                    for row in background_initialization(spec):
                        lo,hi=t['slices'][row['slice']];self.assertLessEqual(lo+row['count'],hi)
                        ranges.append(set(range(lo,lo+row['count'])))
                    self.assertEqual(sum(map(len,ranges)),len(set.union(*ranges)))
                    self.assertTrue(all(not r.intersection(range(*t['slices']['login'])) for r in ranges))

    def test_smoke_diagnostics_do_not_pass_or_hide_functional_error(self):
        summary={'errors':[],'counts':[{'metric':'phase14_results','tags':['main','availability','business_success'],'count':1}],
                 'trends':[{'metric':'phase14_duration_ms','tags':['main','availability','business_success'],'p95':99999,'p99':99999}]}
        for smoke in (False,True):
            result=verdict(summary,{'passed':True},{'passed':False,'errors':['window too short']},{'isolated':True},load_targets(smoke=smoke),smoke=smoke,overload=True)
            self.assertEqual(result['overload_protection']['status'],'not_applicable' if smoke else 'fail')
            if smoke:
                self.assertEqual(result['functional']['status'],'pass');self.assertEqual(result['formal_recovery']['status'],'not_applicable')
                self.assertFalse(result['diagnostic']['formalRecovery']['passed']);self.assertTrue(result['diagnostic']['latencyFailures'])
        for field in ('counts','trends'):
            empty=copy.deepcopy(summary);empty[field]=[]
            self.assertEqual(verdict(empty,{'passed':True},{},{'isolated':False},load_targets(smoke=True),smoke=True)['functional']['status'],'fail')
        for error in ('dropped iterations','interrupted','missing shard'):
            broken=copy.deepcopy(summary);broken['errors']=[error]
            self.assertEqual(verdict(broken,{'passed':True},{},{'isolated':False},load_targets(smoke=True),smoke=True)['functional']['status'],'fail')
        self.assertEqual(verdict(summary,{'passed':False},{},{'isolated':False},load_targets(smoke=True),smoke=True)['functional']['status'],'fail')

    def test_browser_contract_rejects_extra_missing_and_serialized_requests(self):
        script="""import {validateColdStartup as check} from './performance/scripts/phase14_browser_contract.mjs';
import fs from 'node:fs';import assert from 'node:assert/strict';
const x=JSON.parse(fs.readFileSync('performance/results/phase14-browser-v3-cold-20260910/browser.json')).authenticatedInitial;
assert(check(x).passed);
for(const transform of [x=>x.requests.pop(),x=>x.requests.push(x.requests[0]),x=>x.requests[1].startedAfterMs=x.requests[0].finishedAfterMs+1]){const b=structuredClone(x);transform(b);assert(!check(b).passed);}
"""
        # The checked-in minimal trace fixture makes this test independent of ignored run files.
        script=script.replace('performance/results/phase14-browser-v3-cold-20260910/browser.json','performance/tests/fixtures/phase14-cold-startup.json')
        r=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
