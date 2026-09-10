import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
import run_phase14 as runner
from phase14_verify import capture_temporary_owners
from phase14_sampling import pg_delta, LightPostgresSampler
from phase14_model import load_targets, online_plan


def compose_model():
    return {'name':'phase14-test','volumes':{k:{'name':'phase14-test_'+k} for k in ('postgres','prometheus')},
            'services':{'backend':{'environment':{'TICKETING_PAYMENT_PROVIDER':'simulation'},'command':['./ticketing_backend','config/config.phase14.json']},
                        'postgres':{'environment':{'POSTGRES_DB':'ticketing'}}}}


class RunnerTests(unittest.TestCase):
    def test_light_postgres_sampling_has_independent_cadence_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=Mock(root=Path(tmp));ready=threading.Event();calls=[]
            def read(_):
                calls.append(1)
                if len(calls)>=2:ready.set()
                return {'time':time.time(),'activeWaits':0,'lockWaits':0}
            with patch('phase14_sampling.postgres',side_effect=read):
                sampler=LightPostgresSampler(env,.01,read=lambda:read(env)).start()
                self.assertTrue(ready.wait(2));result=sampler.stop()
            self.assertEqual(result['intervalSeconds'],.01);self.assertGreaterEqual(result['samples'],2)
            self.assertEqual(result['errors'],[]);self.assertFalse(sampler.thread.is_alive())
            self.assertEqual(len((Path(tmp)/'postgres-light.jsonl').read_text().splitlines()),result['samples'])

    def test_light_postgres_read_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp, patch('phase14_sampling.postgres',side_effect=RuntimeError('read failed')):
            sampler=LightPostgresSampler(Mock(root=Path(tmp)),.01,read=lambda:__import__('phase14_sampling').postgres(None)).start();sampler.thread.join(timeout=2)
            result=sampler.stop();self.assertTrue(result['errors']);self.assertEqual(result['samples'],0)

    def test_resource_preflight_rejects_new_swap_before_load(self):
        sample={k:False for k in ('swapping','oom','restarted','unhealthy','networkExhausted','fdExhausted')}
        sample.update(memoryFraction=.1,clockSkewMs=0)
        cal={'idleSamples':[dict(sample),dict(sample)]};t=load_targets(smoke=True)
        self.assertTrue(runner.resource_preflight(cal,t)['passed'])
        cal['idleSamples'][1]['swapping']=True
        self.assertFalse(runner.resource_preflight(cal,t)['passed'])
        self.assertFalse(runner.resource_preflight({'idleSamples':[]},t)['passed'])

    def test_preflight_smoke_swap_warning_and_formal_stop(self):
        from test_phase14_evidence import sample
        x=sample();x.update(swapping=True,swapInDelta=12,swapOutDelta=0)
        cal={'idleSamples':[x,x]}
        result=runner.resource_preflight(cal,load_targets(smoke=True))
        self.assertTrue(result['passed']);self.assertEqual(result['warnings'][0]['code'],'host_swap_activity')
        self.assertFalse(runner.resource_preflight(cal,load_targets())['passed'])

    def test_smoke_system_error_stops_without_waiting_for_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'shards/0';folder.mkdir(parents=True)
            (folder/'raw.json').write_text(json.dumps({'type':'Point','metric':'phase14_results',
                'data':{'time':'2026-09-10T00:00:01Z','value':1,'tags':{'result':'system_error'}}})+'\n')
            now=runner.timestamp('2026-09-10T00:00:02Z')
            self.assertEqual(runner.RawProgress(load_targets(smoke=True)).read(root,now),(True,0))
            self.assertEqual(runner.RawProgress(load_targets()).read(root,now),(False,0))

    def test_reset_retains_containers_and_volumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=runner.Environment(load_targets(smoke=True),tmp);env.validate=Mock();env.http=Mock()
            env.compose=Mock(return_value=Mock(stdout=b'0'))
            env.reset(yes=True)
            calls=[c.args for c in env.compose.call_args_list]
            self.assertTrue(any(c[:2]==('stop','backend') for c in calls))
            self.assertIn(('exec','-T','redis','redis-cli','FLUSHALL','SYNC'),calls)
            self.assertFalse(any(x in ('down','rm','prune','-v','--volumes') for c in calls for x in c))

    def test_login_background_control_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots=[Path(tmp)/name for name in ('control','login')];t=load_targets(smoke=True)
            for root in roots:
                root.mkdir();spec=runner.build_spec(t,'L1','phase14-test',passed_u1=[20],passed_u2=[20]);spec['releaseAtMs']=100000;spec['shards']=[{'shard':'0'}]
                (root/'spec.json').write_text(json.dumps(spec))
            def summary(count,p95):
                return {'trends':[{'metric':'phase14_duration_ms','tags':[scenario,step,'business_success'],'count':count,'p95':p95}
                    for scenario,step in [('background_refresh','availability'),('background_hold','journey'),('background_order','journey')]]}
            with patch.object(runner,'aggregate',side_effect=[summary(100,100),summary(90,150)]):
                self.assertTrue(runner.compare_background(*roots,t)['diagnostic']['passed'])
            for count,p95 in ((89,100),(100,151)):
                with patch.object(runner,'aggregate',side_effect=[summary(100,100),summary(count,p95)]):
                    self.assertFalse(runner.compare_background(*roots,t)['diagnostic']['passed'])

    def test_redis_owner_and_ttl_require_real_checkout(self):
        t=load_targets(smoke=True);spec=runner.build_spec(t,'H1','phase14-test',path='temporary')
        env=Mock();env.sql.return_value='1';env.compose.return_value.stdout=json.dumps([['checkout-a|0',299],['checkout-b|1',298]]).encode()
        self.assertTrue(capture_temporary_owners(env,spec)['passed'])
        self.assertIn("status='SELECTING'",env.sql.call_args.args[0])
        env.compose.return_value.stdout=json.dumps([['checkout-a|0',-1],['checkout-b|1',298]]).encode()
        self.assertFalse(capture_temporary_owners(env,spec)['passed'])
        env.compose.return_value.stdout=json.dumps([['invalid',299],['checkout-b|1',298]]).encode()
        self.assertFalse(capture_temporary_owners(env,spec)['passed'])
        env.sql.return_value='0';self.assertFalse(capture_temporary_owners(env,spec)['passed'])

    def test_postgres_deltas_track_statement_io_and_reset(self):
        before={'postmasterStart':'same','database':{'stats_reset':'same','xact_commit':1},'wal':{'stats_reset':'same','wal_bytes':5},
            'statementsInfo':{'stats_reset':'same','dealloc':0},'statements':[{'queryid':42,'calls':2}],
            'io':[{'backend_type':'client backend','object':'relation','context':'normal','reads':3,'stats_reset':'same'}]}
        after=copy.deepcopy(before);after['statements'][0]['calls']=4;after['io'][0]['reads']=7
        result=pg_delta(before,after);self.assertTrue(result['valid'])
        self.assertEqual(result['statements'][0]['delta'],{'calls':2})
        self.assertEqual(result['io'][0]['delta'],{'reads':4})
        for mutation in (lambda x:x.update(postmasterStart='restart'),lambda x:x['wal'].update(stats_reset='reset'),
                         lambda x:x['statementsInfo'].update(dealloc=1),lambda x:x.update(statements=[]),
                         lambda x:x['io'][0].update(stats_reset='reset')):
            broken=copy.deepcopy(after);mutation(broken);self.assertFalse(pg_delta(before,broken)['valid'])

    def test_raw_progress_reads_appends_once_and_preserves_partial_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'shards/0';folder.mkdir(parents=True);path=folder/'raw.json'
            line=json.dumps({'type':'Point','metric':'dropped_iterations','data':{'value':1}})
            path.write_text(line[:20]);reader=runner.RawProgress(load_targets())
            self.assertEqual(reader.read(root,now=0),(False,0))
            with path.open('a') as f:f.write(line[20:]+'\n')
            self.assertEqual(reader.read(root,now=0),(False,1))
            self.assertEqual(reader.read(root,now=0),(False,1))
            with path.open('a') as f:f.write(line+'\n')
            self.assertEqual(reader.read(root,now=0),(False,2))

    def test_cleanup_guard_rejects_wrong_project_volume_network_and_path(self):
        t=load_targets();m=compose_model();data=runner.GENERATED/'smoke'
        self.assertEqual(runner.guard_model(m,'phase14-test',data,t),['phase14-test_postgres','phase14-test_prometheus'])
        for name in ('','*','phase14-*','ticketing','../phase14-test'):
            with self.assertRaises(ValueError):runner.guard_model(m,name,data,t)
        for mutation in (
            lambda m:m['volumes']['postgres'].update(name='development-data'),
            lambda m:m['volumes']['postgres'].update(external=True),
            lambda m:m.update(networks={'old':{'external':True}}),
            lambda m:m['services']['backend'].update(network_mode='host'),
            lambda m:m['services']['backend'].update(volumes=[{'type':'bind','source':str(ROOT.anchor),'read_only':True}]),
            lambda m:m['services']['backend']['environment'].update(TICKETING_PAYMENT_PROVIDER='stripe'),
        ):
            v=copy.deepcopy(m);mutation(v)
            with self.assertRaises(ValueError):runner.guard_model(v,'phase14-test',data,t)
        with self.assertRaises(ValueError):runner.guard_model(m,'phase14-test',ROOT,t)

    def test_reset_without_yes_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=runner.Environment(load_targets(smoke=True),tmp);env.validate=Mock();env.compose=Mock()
            env.reset();env.validate.assert_called_once();env.compose.assert_not_called()

    def test_shared_guard_preserves_business_curve_plan_and_window(self):
        for smoke in (False,True):
            t=load_targets(smoke=smoke);n=t['burst']['users']
            for case in ('G0','U2','J1','O1','H1','H2','H3','L1','L2'):
                with patch.object(runner,'guard_delivery',return_value={}):
                    original=runner.build_spec(t,case,'test',passed_u1=[n],passed_u2=[n])
                guarded=runner.build_spec(t,case,'test',passed_u1=[n],passed_u2=[n])
                for key in ('mapping','plan','loadSeconds'):self.assertEqual(original[key],guarded[key])
                for name,row in guarded['deliverySchedule'].items():
                    self.assertEqual(row['businessExecutor'],original['scenarios'][name])
                    actual=guarded['scenarios'][name];prior=original['scenarios'][name]
                    for key in ('rate','timeUnit','startRate','startTime','exec'):
                        self.assertEqual(actual.get(key),prior.get(key))
                    if 'stages' in prior:self.assertEqual(actual['stages'][:-1],prior['stages'])
                    self.assertEqual(row['executorWindowSeconds']-row['businessWindowSeconds'],1)

    def test_stopped_fault_fixture_is_historical_but_current_oom_retained(self):
        from phase14_sampling import scoped_containers
        fixture={'id':'old','service':'backend-failure','state':'exited','healthy':'unhealthy'}
        core={'id':'db','service':'postgres','state':'running'}
        gen={'id':'g','service':'k6','state':'running'};seen=set()
        current,bad=scoped_containers([fixture,core,gen],seen)
        self.assertEqual(current,[core,gen]);self.assertEqual(bad,[])
        gen.update(state='exited',oom=True)
        self.assertIn(gen,scoped_containers([fixture,core,gen],seen)[0])
        fixture['state']='running';self.assertEqual(scoped_containers([fixture,core],seen)[1],['old'])

    def test_persistent_reader_reuses_pipe_and_fails_on_eof(self):
        import queue
        from phase14_pg_stream import ActivityConnection
        c=ActivityConnection.__new__(ActivityConnection);c.process=Mock();c.lines=queue.Queue()
        c.lines.put('{"one":1}\n');c.lines.put('{"two":2}\n');c.lines.put(None)
        self.assertEqual(c.sql('SELECT 1;'),'{"one":1}');self.assertEqual(c.sql('SELECT 2;'),'{"two":2}')
        self.assertEqual(c.process.stdin.write.call_count,2)
        with self.assertRaises(RuntimeError):c.sql('SELECT 3;')

    def test_persistent_cleanup_targets_owned_connection_only(self):
        import subprocess
        from phase14_pg_stream import ActivityConnection
        c=ActivityConnection.__new__(ActivityConnection);c.env=Mock();c.reader=Mock();c.process=Mock();c.pid=42;c.birth='2026-09-10T00:00:00Z'
        c.process.poll.return_value=None;c.process.wait.side_effect=[subprocess.TimeoutExpired('fixture',7),0]
        c.close();query=c.env.sql.call_args.args[0]
        self.assertIn('pid=42',query);self.assertIn("backend_start='2026-09-10T00:00:00Z'",query)
        self.assertIn("application_name='phase14_sampler'",query)

    def test_every_case_has_bounded_plans_and_isolated_payment(self):
        for smoke in (False,True):
            t=load_targets(smoke=smoke);n=t['burst']['users']
            for case in ('G0','U1','U2','J1','O1','H1','H2','H3','L1','L2','S1'):
                spec=runner.build_spec(t,case,'phase14-test',passed_u1=[n],passed_u2=[n])
                self.assertEqual(set(spec['plan']),set(spec['scenarios']))
                for name,scenario in spec['scenarios'].items():
                    if 'arrival-rate' in scenario['executor']:
                        self.assertGreater(scenario['preAllocatedVUs'],0)
                        self.assertNotIn('maxVUs',scenario)
                if case in t['probes']['paymentScenarios']:
                    self.assertEqual(spec['plan']['payment'],spec['loadSeconds']*t['probes']['paymentRate'])
                    self.assertGreater(spec['scenarios']['payment']['preAllocatedVUs'],min(spec['plan']['payment'],n))
                else:self.assertNotIn('payment',spec['plan'])
            with self.assertRaises(ValueError):runner.build_spec(t,'L1','phase14-test')

    def test_open_entries_equal_frozen_population_and_integral(self):
        t=load_targets();spec=runner.build_spec(t,'U2','phase14-test')
        self.assertEqual(sum(v for k,v in spec['plan'].items() if k.startswith('enter_')),10000)
        for i,row in enumerate(online_plan(t)):
            self.assertEqual(spec['plan']['refresh_'+str(i)],int(row['refreshIntegral']))
        a=runner.build_spec(t,'J1','phase14-a');b=runner.build_spec(t,'J1','phase14-b')
        self.assertNotEqual(a['idempotencyNamespace'],b['idempotencyNamespace'])
        self.assertEqual(a['targets']['slices'],b['targets']['slices'])

    def test_common_exporter_does_not_require_new_business_grants(self):
        common=(ROOT/'performance/postgres-exporter/queries.yml').read_text(encoding='utf-8')
        dedicated=(ROOT/'performance/phase14/queries.yml').read_text(encoding='utf-8')
        self.assertNotIn('FROM orders',common)
        self.assertIn('FROM orders',dedicated)
        for text in (common,dedicated):
            self.assertIn("state = 'active' AND wait_event IS NOT NULL",text)
            self.assertIn("backend_type = 'client backend'",text)
            self.assertIn('idle in transaction (aborted)',text)


if __name__=='__main__':unittest.main()
