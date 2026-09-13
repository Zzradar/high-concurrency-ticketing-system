"""Counterexamples for the second protocol candidate's explicit bootstrap/export."""
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/'performance/experiments/phase19-global-polling-mixed-load/diagnostics/protocol-r2-candidate'
sys.path.insert(0,str(CANDIDATE))
spec=importlib.util.spec_from_file_location('phase19_candidate_measure',CANDIDATE/'measure.py')
measure=importlib.util.module_from_spec(spec);spec.loader.exec_module(measure)


class CandidateProtocolTests(unittest.TestCase):
    def test_bootstrap_is_separate_and_does_not_lower_formal_arrival_plan(self):
        counts={}
        for metric in ['phase19_started','phase19_completed']:
            counts[metric+'|'+json.dumps({'kind':'bootstrap','scenario':'bootstrap'})]=200
            for stream in range(10):
                counts[metric+'|'+json.dumps({'kind':'read','scenario':'readers'+str(stream)})]=3000
        point={'counts':counts}
        result=measure.accounting(point,'open',150,250,0,20,30,200)
        self.assertEqual(result['planned']['readerIterationsNominal'],30000)
        self.assertEqual(result['planned']['bootstrapSnapshots'],200)
        self.assertEqual(result['errors'],[])
        for metric in ['phase19_started','phase19_completed']:
            counts[metric+'|'+json.dumps({'kind':'read','scenario':'readers0'})]=2999
        self.assertIn('reader arrival stream 0 differs from plan',measure.accounting(point,'open',150,250,0,20,30,200)['errors'])

    def test_missing_bootstrap_is_invalid_even_when_all_reads_completed(self):
        counts={}
        for metric in ['phase19_started','phase19_completed']:
            for stream in range(10):
                counts[metric+'|'+json.dumps({'kind':'read','scenario':'readers'+str(stream)})]=3000
        self.assertIn('per-VU bootstrap count differs from plan',measure.accounting({'counts':counts},'open',150,250,0,20,30,200)['errors'])

    def test_native_gzip_preserves_all_status_populations_and_counts(self):
        points=[{'type':'Point','metric':'http_req_duration','data':{'value':value,'tags':{'name':'GET delta','phase':'observe','status':status}}}
            for value,status in [(10,'200'),(20,'200'),(1,'503')]]
        points.append({'type':'Point','metric':'phase19_started','data':{'value':1,'tags':{'kind':'read','phase':'observe'}}})
        raw=('\n'.join(map(json.dumps,points))+'\n').encode()
        with tempfile.TemporaryDirectory() as folder:
            plain=Path(folder)/'points.jsonl';plain.write_bytes(raw)
            compressed=Path(folder)/'points.jsonl.gz';compressed.write_bytes(gzip.compress(raw))
            self.assertEqual(measure.aggregate(plain),measure.aggregate(compressed))
            compressed.write_bytes(compressed.read_bytes()[:-8])
            with self.assertRaises(EOFError): measure.aggregate(compressed)


if __name__=='__main__':unittest.main()

class QualificationStartupTests(unittest.TestCase):
    def test_qualification_keeps_observe_window_after_real_sut_spread(self):
        protocol=Path(__file__).resolve().parents[1]/'experiments/phase19-global-polling-mixed-load/protocol'
        code=(protocol/'calibrate.py').read_text()
        self.assertIn('INIT_SPREAD_SECONDS=30',code)
        self.assertIn('WARMUP_SECONDS=45',code)
        self.assertIn('SECONDS={args.seconds+45}',code)
