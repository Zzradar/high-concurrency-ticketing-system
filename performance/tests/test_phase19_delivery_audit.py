import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase19_delivery_audit import valid_capacity, verifier, index_matches, verify_git_batch

class DeliveryAuditTests(unittest.TestCase):
    def good(self):
        return dict(valid=True,diagnostic=False,exitCode=0,metricSummaryAvailable=True,
                    interruptedIterations=0,droppedIterations=0,startedIterations=5,
                    completedBusinessIterations=5,k6CompletedIterations=5,
                    accounting=dict(errors=[],startedByKind={'read':4,'cancel':1},completedByKind={'read':4,'cancel':1}))
    def test_rejects_missing_summary_even_with_zero_error_counters(self):
        point=self.good();point['metricSummaryAvailable']=False
        with self.assertRaises(ValueError):valid_capacity(point)
    def test_rejects_dropped_or_business_type_substitution(self):
        for field in ['droppedIterations','interruptedIterations']:
            point=self.good();point[field]=1
            with self.assertRaises(ValueError):valid_capacity(point)
        point=self.good();point['accounting']['completedByKind']={'read':5}
        with self.assertRaises(ValueError):valid_capacity(point)
    def test_rejects_invalid_or_diagnostic_even_when_iterations_match(self):
        for field,value in [('valid',False),('diagnostic',True)]:
            point=self.good();point[field]=value
            with self.assertRaises(ValueError):valid_capacity(point)
        valid_capacity(self.good())
    def test_verifier_flag_cannot_hide_violation_or_empty_checks(self):
        for checks in [{},{'oversell':1}]:
            with self.assertRaises(ValueError):verifier({'passed':True,'checks':checks})
        verifier({'passed':True,'checks':{'oversell':0}})
    def test_index_rejects_unindexed_or_changed_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'point.json';p.write_bytes(b'{}')
            idx={'files':{'point.json':{'sha256':hashlib.sha256(b'{}').hexdigest(),'bytes':2}}}
            (root/'EVIDENCE_SHA256.json').write_text(json.dumps(idx))
            self.assertEqual(index_matches(root),1)
            p.write_bytes(b'[]')
            with self.assertRaises(ValueError):index_matches(root)
            p.write_bytes(b'{}');(root/'extra.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):index_matches(root)

    def test_committed_lf_cannot_satisfy_hash_bound_crlf_evidence(self):
        original=b'one\r\ntwo\r\n';converted=b'one\ntwo\n'
        expected={'point':{'sha256':hashlib.sha256(original).hexdigest(),'bytes':len(original)}}
        def batch(body):return b'abc blob '+str(len(body)).encode()+b'\n'+body+b'\n'
        verify_git_batch(batch(original),expected)
        with self.assertRaises(ValueError):verify_git_batch(batch(converted),expected)

    def test_committed_missing_file_cannot_pass_working_tree_check(self):
        expected={'missing':{'sha256':hashlib.sha256(b'x').hexdigest(),'bytes':1}}
        with self.assertRaises(ValueError):verify_git_batch(b'HEAD:missing missing\n',expected)
