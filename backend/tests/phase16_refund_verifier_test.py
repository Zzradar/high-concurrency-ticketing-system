"""Run after the real browser buyer-refund fixture; negative mutations roll back."""
from pathlib import Path
import unittest
from phase16_api_test import sql
ROOT=Path(__file__).resolve().parents[2]
VERIFIER=(ROOT/'performance/verification/verify.sql').read_text(encoding='utf-8')
class RefundVerifierTest(unittest.TestCase):
    def results(self,prefix=''):
        raw=sql('BEGIN;'+prefix+VERIFIER+'ROLLBACK;')
        return {name:int(value) for name,value in (line.rsplit('|',1) for line in raw.splitlines())}
    def test_completed_buyer_refund_is_valid(self):
        self.assertGreater(int(sql("SELECT count(*) FROM refunds r JOIN orders o ON o.id=r.order_id WHERE o.user_id='perf-user-160001' AND r.source='BUYER' AND r.status='SUCCEEDED';")),0)
        self.assertTrue(all(v==0 for v in self.results().values()))
    def test_missing_refund_remains_invalid(self):
        values=self.results("DELETE FROM refunds r USING orders o WHERE o.id=r.order_id AND o.user_id='perf-user-160001' AND r.source='BUYER';")
        self.assertGreater(values['accepted_payment_mismatch'],0)
        self.assertGreater(values['order_paid_at_mismatch'],0)
    def test_wrong_refund_amount_remains_invalid(self):
        values=self.results("UPDATE refunds r SET amount=amount+1 FROM orders o WHERE o.id=r.order_id AND o.user_id='perf-user-160001' AND r.source='BUYER';")
        for name in ['accepted_payment_mismatch','order_paid_at_mismatch','refund_order_or_amount_mismatch']:
            self.assertGreater(values[name],0)
if __name__=='__main__':unittest.main(verbosity=2)
