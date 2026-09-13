import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import json
from copy import deepcopy

PROTOCOL=Path(__file__).resolve().parents[1]/'experiments/phase19-global-polling-mixed-load/protocol'
sys.path.insert(0,str(PROTOCOL))
spec=importlib.util.spec_from_file_location('phase19_measure',PROTOCOL/'measure.py')
measure=importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class MeasurementTests(unittest.TestCase):
    def test_completed_iterations_do_not_hide_missing_planned_arrivals(self):
        counts={}
        for scenario in range(10):
            for metric in ['phase19_started','phase19_completed']:
                counts[metric+'|'+json.dumps({'kind':'read','scenario':'readers'+str(scenario)})]=1
        point={'counts':counts}
        self.assertEqual(measure.accounting(point,'open',1,10,0,20)['errors'],[])
        for metric in ['phase19_started','phase19_completed']:
            counts[metric+'|'+json.dumps({'kind':'read','scenario':'readers0'})]=0
        self.assertIn('reader arrival stream 0 differs from plan',measure.accounting(point,'open',1,10,0,20)['errors'])

    def test_rejections_have_separate_latency_population(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'points.jsonl'
            path.write_text('\n'.join(json.dumps({'type':'Point','metric':'http_req_duration','data':{'value':value,'tags':{'name':'GET delta','phase':'observe','status':status}}}) for status,value in [('200',10),('200',30),('503',1)]))
            result=measure.aggregate(path)['httpDurationMs']
        self.assertEqual(result['GET delta|observe|200']['p95'],30)
        self.assertEqual(result['GET delta|observe|200']['samples'],2)
        self.assertEqual(result['GET delta|observe|503']['samples'],1)

    def test_stream_entry_count_survives_length_trimming(self):
        before={'formalVersionSum':10,'projectedFormalVersionSum':10,'generations':{'s':'g'},'streams':{'s/z':{'entries-added':10000,'length':10000}}}
        after=deepcopy(before)
        after.update(formalVersionSum=12,projectedFormalVersionSum=12)
        after['streams']['s/z']['entries-added']=10005
        result=measure.inventory_delta(before,after)
        self.assertEqual(result['formalGenerated'],2)
        self.assertEqual(result['temporaryVisibleEntriesAdded'],3)
        self.assertTrue(result['generationsUnchanged'])
        after['generations']['s']='new'
        self.assertFalse(measure.inventory_delta(before,after)['generationsUnchanged'])

    def test_missing_generation_is_not_a_valid_stable_generation(self):
        point={'formalVersionSum':0,'projectedFormalVersionSum':0,'generations':{'s':None},'streams':{}}
        self.assertFalse(measure.inventory_delta(point,point)['generationsUnchanged'])


if __name__=='__main__':unittest.main()
