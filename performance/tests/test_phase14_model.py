import collections
import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'performance/scripts'),str(ROOT/'performance/data')]
import phase14_model as model
import generate_dataset as data


class Phase14ModelTests(unittest.TestCase):
    def test_small_h2_scope_reaches_both_activities(self):
        t=model.load_targets(smoke=True)
        targets=collections.Counter(model.hotspot(i,t,session_count=20)['sessionId'] for i in range(20))
        self.assertEqual(targets,{'perf-session-001-001':10,'perf-session-002-001':10})
    def test_frozen_shapes_and_smoke_are_separate(self):
        t=model.load_targets(); s=model.load_targets(smoke=True)
        self.assertEqual(t['dataset']['activeAuthSessions'],100000)
        self.assertEqual(t['dataset']['registeredUsers'],1000000)
        self.assertEqual(s['mode'],'smoke')
        self.assertEqual(t['sourceSha256'],s['sourceSha256'])
        p,_=data.load_profile('phase14-1m-users-100k-auth')
        self.assertEqual(data.validate_profile(p),data.DatasetShape(1000000,100000,2,20,5000,100000))

    def test_groups_exact_and_repeatable(self):
        t=model.load_targets()
        groups=[model.group(i,t) for i in range(10000)]
        self.assertEqual(collections.Counter(groups),{'browse':6000,'hold':2500,'order':1500})
        self.assertEqual(groups,[model.group(i,t) for i in range(10000)])
        t['seed']+=1
        self.assertNotEqual(groups,[model.group(i,t) for i in range(10000)])

    def test_hotspots_exact_for_each_scope_and_shard(self):
        t=model.load_targets()
        for count in [1,10,20]:
            slots=collections.Counter(tuple(model.hotspot(i,t,session_count=count).values()) for i in range(10000))
            self.assertEqual(len(slots),1000)
            self.assertEqual(set(slots.values()),{10})
            self.assertEqual(len({x[0] for x in slots}),count)
        self.assertEqual(len({tuple(model.hotspot(i,t,single=True).values()) for i in range(10000)}),1)
        points=model.segments(3,t)
        self.assertEqual(points[0]['sequence'],'0,1/3,2/3,1')
        self.assertEqual(points[0]['segment'].split(':')[1],points[1]['segment'].split(':')[0])

    def test_open_model_integrates_fixed_population(self):
        t=model.load_targets(); p=model.online_plan(t)
        self.assertEqual(sum(x['enterCount'] for x in p),10000)
        self.assertEqual([x['refreshIntegral'] for x in p],['2500','12500','7500','25000','37500','100000'])
        self.assertEqual(p[-1]['startSeconds']+p[-1]['durationSeconds'],1740)
        self.assertEqual(sum(x['enterCount'] for x in model.online_plan(t,1)),10000)

    def test_background_requires_stable_input(self):
        t=model.load_targets()
        with self.assertRaises(ValueError): model.background(t,[],[])
        self.assertEqual(model.background(t,[],[2500])['users'],1750)
        b=model.background(t,[10000],[10000])
        self.assertEqual(Fraction(b['hold']),Fraction(125,24))
        self.assertEqual(Fraction(b['order']),Fraction(25,8))

    def test_invalid_pool_window_or_distribution_fails(self):
        t=model.load_targets()
        for mutate in [lambda x:x['behavior'].update(browse=59),lambda x:x['slices'].update(payment=[0,1]),
                       lambda x:x['hotspot'].update(users=9999),lambda x:x['burst'].update(windowsSeconds=[0]),
                       lambda x:x['dataset'].update(activeAuthSessions=100)]:
            v=copy.deepcopy(t);mutate(v)
            with self.assertRaises(ValueError):model.validate(v)

    def test_stream_export_spreads_from_real_config_and_redacts_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); t=model.load_targets(smoke=True)
            auth=json.loads((ROOT/'backend/config/config.performance.json').read_text())
            auth['custom_config']['authentication']['last_seen_write_interval_seconds']=17
            path=root/'auth.json';path.write_text(json.dumps(auth))
            m=data.export_phase14(root/'data',t,path)
            sql=(root/'data/dataset.sql').read_text()
            self.assertIn('% 17',sql); self.assertNotIn('% 300',sql)
            sessions=json.loads((root/'data/sessions.json').read_text())
            users=json.loads((root/'data/workload-users.json').read_text())
            self.assertEqual(len(sessions),2000)
            self.assertFalse({x['userId'] for x in sessions}&{x['userId'] for x in users})
            self.assertEqual(len({x['sessionToken'] for x in sessions}),2000)
            self.assertLess(m['generation']['pythonPeakAllocatedBytes'],2*1024*1024)
            serialized=json.dumps(m)
            for forbidden in ('sessionToken','csrfToken','Cookie','password','sk_test','whsec'):
                self.assertNotIn(forbidden,serialized)
            for name,info in m['files'].items():self.assertEqual(info['sha256'],data.file_sha256(root/'data'/name))
            with self.assertRaises(data.DatasetError):data.export_phase14(root/'data',t,path)

    def test_disk_shortage_rejected_before_secret_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(data.shutil,'disk_usage',return_value=collections.namedtuple('Disk','total used free')(1,1,0)):
            with self.assertRaises(data.DatasetError):
                data.export_phase14(Path(tmp),model.load_targets(smoke=True),ROOT/'backend/config/config.performance.json')
            self.assertEqual(list(Path(tmp).iterdir()),[])


if __name__=='__main__':unittest.main()
