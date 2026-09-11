import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase14_topology import Topology, SutExecutor, LoadExecutor, verify_container, redact, digest
from phase14_model import load_targets
from phase14_campaign import jobs, plan, sample_errors, verify_hashes, evidence_hashes, qualification_guard, overhead_comparison, run_g0
from phase14_dual import DualEnvironment


def config():
    return dict(mode='dual',sutSshAlias='phase14-sut',sutWorkdir='/srv/phase14/repo',
                sutBaseUrl='http://10.12.34.56:18414',sutBindAddress='10.12.34.56',
                sutProject='phase14-formal-sut',loadProject='phase14-formal-load',
                loadDockerPrefix=['sudo'],resultRoot='/srv/phase14/repo/performance/results')


class ConfigTests(unittest.TestCase):
    def test_valid_public_configuration_has_no_address(self):
        t=Topology.parse(config(),load_targets())
        text=json.dumps(t.public())
        self.assertNotIn('10.12.34.56',text);self.assertNotIn('http://',text)
        self.assertEqual(t.public()['fingerprint'],digest(config()))

    def test_rejects_unknown_missing_or_unsafe_values(self):
        mutations=[lambda v:v.update(extra=1),lambda v:v.pop('mode'),lambda v:v.update(mode='local'),
                   lambda v:v.update(sutSshAlias='phase14-sut;true'),lambda v:v.update(sutWorkdir='/tmp/repo'),
                   lambda v:v.update(sutWorkdir='../repo'),lambda v:v.update(loadDockerPrefix=['sudo','sh']),
                   lambda v:v.update(sutProject=v['loadProject']),lambda v:v.update(loadProject='phase14-formal-sut'),
                   lambda v:v.update(resultRoot='/tmp/results'),lambda v:v.update(resultRoot='/srv/phase14/repo/performance/results/../x')]
        for mutate in mutations:
            v=config();mutate(v)
            with self.subTest(v=v),self.assertRaises(ValueError):Topology.parse(v,load_targets())
        for address in ('127.0.0.1','0.0.0.0','8.8.8.8','169.254.1.2','::1'):
            v=config();v.update(sutBindAddress=address,sutBaseUrl='http://'+address+':18414')
            with self.assertRaises(ValueError):Topology.parse(v,load_targets())
        for url in ('http://10.12.34.56:1','http://u:p@10.12.34.56:18414','http://10.12.34.56:18414/x',
                    'http://10.12.34.56:18414?q=1','http://10.12.34.56:18414#x','http://10.12.34.57:18414','https://10.12.34.56:18414'):
            v=config();v['sutBaseUrl']=url
            with self.assertRaises(ValueError):Topology.parse(v,load_targets())

    def test_remote_arguments_round_trip_without_shell_injection(self):
        import shlex
        executor=SutExecutor(Topology.parse(config(),load_targets()),Path('unused'))
        args=['printf','%s','$(touch /tmp/forbidden); echo secret',"quote's",'two words']
        argv=executor.argv(args)
        self.assertIn('StrictHostKeyChecking=yes',argv)
        parsed=shlex.split(argv[-1].split(' && exec ',1)[1])
        self.assertEqual(parsed,['env',*args])
        self.assertEqual(LoadExecutor(executor.topology,'unused').argv(args),args)

    def test_stdin_and_failure_logs_do_not_contain_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'commands.jsonl';executor=SutExecutor(Topology.parse(config(),load_targets()),path)
            result=subprocess.CompletedProcess([],7,b'',b'secret database failure')
            with patch('phase14_topology.subprocess.run',return_value=result) as run:
                with self.assertRaises(RuntimeError):executor.run(['psql','-At'],input=b'SECRET SQL BODY')
                self.assertEqual(run.call_args.kwargs['input'],b'SECRET SQL BODY')
            row=json.loads(path.read_text());self.assertEqual(row['exitCode'],7);self.assertEqual(row['role'],'sut')
            self.assertNotIn('SECRET',path.read_text());self.assertNotIn('secret database',path.read_text())
            with patch('phase14_topology.subprocess.run',side_effect=subprocess.TimeoutExpired('x',1)):
                with self.assertRaises(RuntimeError):executor.run(['true'])
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])['exitCode'],124)

    def test_redaction(self):
        for raw in ('http://user:password@example.com/path','LOGIN_PASSWORD=synthetic','token=private','10.12.34.56'):
            self.assertNotEqual(redact(raw),raw)


def container():
    return {'Id':'owned-id','Name':'/expected','Image':'sha256:expected','Created':'2026-09-11T00:00:01Z',
            'Config':{'Labels':{'com.docker.compose.project':'phase14-formal-load','com.docker.compose.service':'k6','ticketing.phase14.run':'run-1'}},
            'State':{'Running':True}}


class OwnershipTests(unittest.TestCase):
    def test_every_stop_identity_dimension_is_required(self):
        def check(x):return verify_container(x,'phase14-formal-load',{'k6'},run_id='run-1',name='expected',image='sha256:expected',created_after=1789084800)
        self.assertEqual(check(container()),'owned-id')
        for mutate in (lambda x:x.update(Name='/other'),lambda x:x.update(Image='other'),lambda x:x.update(Created='2020-01-01T00:00:00Z'),
                       lambda x:x['Config']['Labels'].update({'com.docker.compose.project':'other'}),
                       lambda x:x['Config']['Labels'].update({'com.docker.compose.service':'backend'}),
                       lambda x:x['Config']['Labels'].update({'ticketing.phase14.run':'old'})):
            x=container();mutate(x)
            with self.assertRaises(ValueError):check(x)

    def test_stop_uses_load_exact_id_and_refuses_unknown_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=DualEnvironment.__new__(DualEnvironment);env.root=Path(tmp)/'run-1';env.root.mkdir()
            env.load_project='phase14-formal-load';env.generators={'expected':{'image':'sha256:expected','createdAfter':1789084800}}
            env.docker=Mock(return_value=Mock(stdout=json.dumps([container()]).encode(),returncode=0))
            self.assertEqual(env.stop_generators(),['owned-id'])
            env.docker.assert_called_with('load','stop','--time','2','owned-id')
            with self.assertRaises(ValueError):env.stop_generators(['unknown'])

    def test_role_whitelist_rejects_before_transport(self):
        env=DualEnvironment.__new__(DualEnvironment);env.models={};env.resolve=Mock()
        for role,args in [('load',('up','-d','backend')),('sut',('stop','k6')),('sut',('stop',)),('load',('down',))]:
            with self.assertRaises(ValueError):env.compose_role(role,*args)
        env.resolve.assert_not_called()

    def test_psql_factory_is_used(self):
        from phase14_pg_stream import ActivityConnection
        import io
        env=Mock();process=env.psql_popen.return_value;process.stdout=io.StringIO('');process.poll.return_value=0
        with patch.object(ActivityConnection,'sql',return_value='{"pid":42,"birth":"2026-09-11T00:00:00Z"}'):
            c=ActivityConnection(env);self.assertIs(c.process,process);c.close()
        env.psql_popen.assert_called_once_with()


class QualificationTests(unittest.TestCase):
    def test_formal_guard_requires_all_explicit_arguments(self):
        for change in ({'yes':False},{'formal_approved':False},{'qualification':None}):
            args=argparse.Namespace(yes=True,formal_approved=True,qualification=Path('q.json'))
            vars(args).update(change)
            with self.assertRaises(ValueError):qualification_guard(args,Mock(dual=True))
        with self.assertRaises(ValueError):qualification_guard(argparse.Namespace(yes=True,formal_approved=True,qualification=Path('x')),Mock(dual=False))

    def test_evidence_corruption_missing_and_traversal_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'evidence.json';p.write_text('original');hashes=evidence_hashes(root)
            verify_hashes(root,hashes);p.write_text('changed')
            with self.assertRaises(ValueError):verify_hashes(root,hashes)
            p.unlink()
            with self.assertRaises(ValueError):verify_hashes(root,hashes)
            with self.assertRaises(ValueError):verify_hashes(root,{'../outside':'0'})
            with self.assertRaises(ValueError):verify_hashes(root,{})

    def test_each_fingerprint_change_refuses_formal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'qualification.json'
            base={k:'frozen' for k in ('git','targets','image','data','snapshot','topology')}
            write={'status':'pass','topologyMode':'dual','createdAt':__import__('time').time(),'fingerprint':base}
            path.write_text(json.dumps(write));args=argparse.Namespace(yes=True,formal_approved=True,qualification=path)
            env=Mock(dual=True,t=load_targets())
            for key in base:
                changed={**base,key:'changed'}
                with patch('phase14_campaign.current_fingerprint',return_value=changed):
                    with self.assertRaises(ValueError):qualification_guard(args,env,immediate=False)

    def test_fixed_job_order_and_no_g0_in_formal(self):
        t=load_targets();j=jobs(t);names=[x[0] for x in j]
        self.assertEqual(len(j),24);self.assertNotIn('G0',names)
        self.assertEqual(names[:11],['U1','U1','U2','U2','J1','J1','J1','O1','O1','O1','E1'])
        self.assertEqual(names[-5:],['L1','L1','L2','L2','S1'])
        self.assertEqual(len(jobs(load_targets(smoke=True),smoke=True)),25)
        p=plan(t);self.assertEqual(len(p['jobs']),24);self.assertEqual(p['targetsSha256'],t['sourceSha256'])
        self.assertEqual(p['jobs'][0]['businessSecondsUpperBound'],1740)
        self.assertEqual(p['jobs'][-1]['businessSecondsUpperBound'],1800)

    def test_role_samples_and_consecutive_gaps_are_required(self):
        t=load_targets();x={'time':0,'loadHost':{'ok':True},'sutHost':{'ok':True},'sutContainers':[{}]}
        self.assertEqual(sample_errors([x,{**x,'time':1}],t),[])
        self.assertTrue(sample_errors([x,{**x,'time':3},{**x,'time':6}],t))
        self.assertTrue(sample_errors([{**x,'sutHost':None},x],t))
        self.assertEqual(sample_errors([{**x,'sutHost':None},x],t,load_only=True),[])

    def test_overhead_requires_abba_and_frozen_threshold(self):
        rows=[{'sampling':b,'p95':10,'p99':20} for b in (False,True,True,False)]
        self.assertTrue(overhead_comparison(rows,.05)['passed'])
        rows[1]['p95']=20;self.assertFalse(overhead_comparison(rows,.05)['passed'])
        self.assertFalse(overhead_comparison(rows[:3],.05)['passed'])

    def test_failed_formal_g0_leg_stops_without_sut_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=Mock(root=Path(tmp),topology=Mock(values={'resultRoot':tmp}))
            child=Mock(root=Path(tmp)/'child');child.root.mkdir();env.child.return_value=child
            (child.root/'g0.json').write_text(json.dumps({'errors':['generator memory'],'longestScenarioDiskBudgetBytes':100}))
            env.load.run.return_value.stdout=b'commit'
            with patch('phase14_campaign.g0_leg',return_value=1) as leg:
                self.assertEqual(run_g0(Mock(),load_targets(),env),1)
                leg.assert_called_once()
            for method in (env.sut.run,env.reset,env.sql,env.http,env.validate):method.assert_not_called()

    def test_checked_in_plan_is_generated_from_frozen_targets(self):
        import hashlib
        actual=json.loads((ROOT/'docs/phase14_formal_plan.json').read_text(encoding='utf-8'))
        expected=plan(load_targets())
        expected['targetsSha256']=hashlib.sha256(subprocess.check_output(['git','show','HEAD:performance/baseline/phase14-targets.json'],cwd=ROOT)).hexdigest()
        self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
