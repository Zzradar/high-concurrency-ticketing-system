import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
import phase14_model as model
import phase14_evidence as evidence


def sample(now=0):
    x={k:False for k in ('correctnessFailure','restarted','oom','unhealthy','wrongEnvironment','swapping','networkExhausted','fdExhausted')}
    x.update({k:0 for k in ('generatorMemoryFraction','generatorCpuFraction','clockSkewMs','dropped','memoryFraction','transactionOldestSeconds','transactionWaiters','httpInflight','hashQueueFraction','seatQueueFraction','hashQueue','seatQueue','redisInflight','pgLockWaits','pgBlocking','pgIdleTransaction','pgIdleAborted')})
    x.update(time=now,completionsSinceLast=1)
    return x


def shard(root,number,values):
    folder=root/'shards'/str(number);folder.mkdir(parents=True)
    lines=[]
    for metric,kind in [('phase14_duration_ms','trend'),('phase14_started','counter'),('phase14_results','counter'),('phase14_iterations_started','counter'),('phase14_iterations_completed','counter')]:
        lines.append({'type':'Metric','metric':metric,'data':{'type':kind}})
    for value in values:
        for metric,v in [('phase14_duration_ms',value),('phase14_started',1),('phase14_results',1),('phase14_iterations_started',1),('phase14_iterations_completed',1)]:
            tags={'shard':str(number),'scenario':'main','step':'confirm'}
            if metric in ('phase14_duration_ms','phase14_results'):tags['result']='business_success'
            lines.append({'type':'Point','metric':metric,'data':{'time':'2026-09-10T00:00:00Z','value':v,'tags':tags}})
    path=folder/'raw.json.gz'
    with gzip.open(path,'wt') as f:
        for item in lines:f.write(json.dumps(item)+'\n')
    (folder/'raw.json.gz.sha256').write_text(evidence.sha256(path))


class Phase14EvidenceTests(unittest.TestCase):
    def test_k6_fractional_seconds_all_rfc3339_precisions(self):
        base=evidence.timestamp('2026-09-09T17:08:12Z')
        for length in range(1,10):
            fraction='389710123'[:length]
            self.assertAlmostEqual(evidence.timestamp('2026-09-09T17:08:12.'+fraction+'Z')-base,float('0.'+fraction[:6]),places=5)

    def test_percentiles_use_all_raw_points_not_shard_averages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shard(root,0,[0]*100);shard(root,1,[1000]*100)
            a=evidence.aggregate(root,[{'shard':'0'},{'shard':'1'}],{'main':200})
            self.assertEqual(a['errors'],[])
            self.assertEqual(a['trends'][0]['p95'],1000)
            self.assertLess((evidence.percentile([0]*100,.95)+evidence.percentile([1000]*100,.95))/2,600)
            self.assertGreater(a['trends'][0]['p95'],600)
            self.assertEqual(a['delivery']['main']['completed'],200)
            self.assertTrue(evidence.aggregate(root,[{'shard':'0'},{'shard':'1'}],{'main':201})['errors'])
            with self.assertRaises(ValueError):evidence.aggregate(root,[{'shard':'0'},{'shard':'0'}],{'main':200})
            with self.assertRaises(OSError):evidence.aggregate(root,[{'shard':'2'}],{'main':200})
            (root/'shards/0/raw.json.gz.sha256').write_text('bad')
            with self.assertRaises(ValueError):evidence.aggregate(root,[{'shard':'0'}],{'main':100})

    def test_corrupt_json_rejected_even_with_valid_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shard(root,0,[1]);p=root/'shards/0/raw.json.gz'
            with gzip.open(p,'wt') as f:f.write('{broken')
            p.with_suffix(p.suffix+'.sha256').write_text(evidence.sha256(p))
            with self.assertRaises(ValueError):evidence.aggregate(root,[{'shard':'0'}],{'main':1})

    def test_stop_error_window_boundaries(self):
        g=evidence.StopGuard(model.load_targets())
        self.assertFalse(g.error_window(100,1))
        self.assertFalse(g.error_window(100,2))
        self.assertTrue(g.error_window(100,2))
        g=evidence.StopGuard(model.load_targets())
        self.assertFalse(g.error_window(99,2));self.assertTrue(g.error_window(99,3))

    def test_stop_continuous_windows_and_login_exemption(self):
        t=model.load_targets()
        for key,value in [('generatorCpuFraction',.8),('transactionWaiters',101),('seatQueueFraction',.9),('hashQueueFraction',.9),('httpInflight',101)]:
            g=evidence.StopGuard(t);s=sample();s.update({key:value,'completionsSinceLast':0})
            self.assertEqual(g.sample(s),[])
            s['time']=9.99;self.assertEqual(g.sample(s),[])
            s['time']=10;self.assertTrue(g.sample(s))
        g=evidence.StopGuard(t,login_protection=True);s=sample();s['hashQueueFraction']=1
        g.sample(s);s['time']=20;self.assertEqual(g.sample(s),[])
        s['memoryFraction']=.91;self.assertTrue(g.sample(s))
        for key,value in [('transactionOldestSeconds',3.01),('generatorMemoryFraction',.9),('dropped',1),('clockSkewMs',101),('correctnessFailure',True),('oom',True),('swapping',True)]:
            g=evidence.StopGuard(t);s=sample();s[key]=value;self.assertTrue(g.sample(s))

    def test_smoke_swap_in_warns_but_all_other_safety_stops_remain(self):
        t=model.load_targets(smoke=True);x=sample();x.update(swapping=True,swapInDelta=12,swapOutDelta=0)
        g=evidence.StopGuard(t)
        self.assertEqual(g.sample(x),[])
        self.assertEqual(g.warnings[0]['code'],'host_swap_activity')
        for key,value in [('oom',True),('restarted',True),('correctnessFailure',True),('dropped',1),('memoryFraction',.91),('swapOutDelta',1)]:
            bad={**x,key:value};self.assertTrue(evidence.StopGuard(t).sample(bad),key)
        for formal in (model.load_targets(),{**t,'burst':{**t['burst'],'users':10000}}):
            self.assertTrue(evidence.StopGuard(formal).sample(x))
        del x['swapOutDelta']
        self.assertTrue(evidence.StopGuard(t).sample(x))

    def test_smoke_warning_cannot_be_capacity_pass(self):
        t=model.load_targets(smoke=True)
        summary={'errors':[],'counts':[],'trends':[]}
        result=evidence.verdict(summary,{'passed':True},{'passed':True},
            {'isolated':True,'warnings':[{'code':'host_swap_activity'}]},t,smoke=True)
        self.assertEqual(result['measurement_validity']['status'],'fail')
        self.assertIn('host_swap_activity',result['measurement_validity']['reasons'])
        self.assertEqual(result['capacity']['status'],'not_applicable')

    def test_guard_ticks_do_not_hide_dropped_or_interrupted_in_any_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shard(root,0,[1]);p=root/'shards/0/raw.json.gz'
            with gzip.open(p,'rt') as f:rows=[json.loads(line) for line in f]
            rows=[x for x in rows if not (x.get('type')=='Point' and x['metric']=='phase14_iterations_completed')]
            rows += [{'type':'Metric','metric':name,'data':{'type':'counter'}} for name in ('dropped_iterations','phase14_scheduler_boundary')]
            rows += [{'type':'Point','metric':name,'data':{'time':'2026-09-10T00:00:00Z','value':1,'tags':{'scenario':'main','shard':'0'}}} for name in ('dropped_iterations','phase14_scheduler_boundary')]
            with gzip.open(p,'wt') as f:
                for x in rows:f.write(json.dumps(x)+'\n')
            p.with_suffix(p.suffix+'.sha256').write_text(evidence.sha256(p))
            summary=evidence.aggregate(root,[{'shard':'0'}],{'main':1})
            self.assertIn('dropped iterations',summary['errors']);self.assertIn('main: missing/interrupted iterations',summary['errors'])
            for smoke in (False,True):
                result=evidence.verdict(summary,{'passed':True},{'passed':True},{'isolated':True},model.load_targets(smoke=smoke),smoke=smoke)
                self.assertEqual(result['measurement_validity']['status'],'fail')

    def test_recovery_requires_continuous_complete_evidence(self):
        t=model.load_targets();rows=[sample(i) for i in range(301)]
        baseline={'httpIdleMax':0,'redisIdleMax':0,'controlP95':{'health':10,'auth':10,'availability':10}}
        controls=[{'time':i/2,'ms':10,'step':step,'result':'business_success'} for i in range(120) for step in baseline['controlP95']]
        self.assertTrue(evidence.recovery(rows,controls,baseline,t,0)['passed'])
        self.assertFalse(evidence.recovery(rows,[],baseline,t,0)['passed'])
        for x in rows:x['transactionWaiters']=1
        self.assertFalse(evidence.recovery(rows,controls,baseline,t,0)['passed'])
        self.assertFalse(evidence.recovery([],controls,baseline,t,0)['passed'])

    def test_no_isolation_or_missing_correctness_never_passes_capacity(self):
        t=model.load_targets();summary={'errors':[],'counts':[],'trends':[]}
        result=evidence.verdict(summary,{'passed':True},{'passed':True},{'isolated':False},t)
        self.assertEqual(result['capacity']['status'],'not_applicable')
        summary['counts']=[{'metric':'phase14_results','tags':['main','auth','business_success'],'count':1}]
        summary['trends']=[{'metric':'phase14_duration_ms','tags':['main','auth','business_success'],'p95':1,'p99':1}]
        result=evidence.verdict(summary,{}, {'passed':True},{'isolated':True},t)
        self.assertEqual(result['capacity']['status'],'fail')

if __name__=='__main__':unittest.main()
