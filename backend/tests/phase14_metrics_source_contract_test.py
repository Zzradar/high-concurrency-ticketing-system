import copy
import json
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]

class Phase14MetricsContracts(unittest.TestCase):
    def test_business_parameters_unchanged(self):
        original=json.loads((ROOT/'config/config.performance.json').read_text(encoding='utf-8'))
        actual=json.loads((ROOT/'config/config.phase14.json').read_text(encoding='utf-8'))
        actual['plugins']=copy.deepcopy(original['plugins'])
        actual['db_clients'][0]['connect_options']=original['db_clients'][0]['connect_options']
        self.assertEqual(actual['custom_config']['payment_simulation']['failure_rate'],0)
        actual['custom_config']['payment_simulation']['failure_rate']=original['custom_config']['payment_simulation']['failure_rate']
        self.assertTrue(actual['custom_config']['performance_metrics'].pop('phase14'))
        self.assertEqual(actual,original)

    def test_every_transaction_call_site_is_observed(self):
        sites=[]
        for path in (ROOT/'src/services').glob('*.cpp'):
            s=path.read_text(encoding='utf-8')
            self.assertNotRegex(s,r'->newTransactionAsync\(')
            sites.extend(re.findall(r'Phase14Metrics::newTransactionAsync\(',s))
        self.assertEqual(len(sites),12)
        for name in ('SeatHoldService','AuthSessionCache','LoginRateLimiter'):
            s=(ROOT/f'src/services/{name}.cpp').read_text(encoding='utf-8')
            self.assertNotIn('->execCommandAsync(',s)
            self.assertIn('Phase14Metrics::execCommandAsync(',s)

    def test_metric_labels_are_bounded_and_hook_boundaries_explicit(self):
        source=(ROOT/'src/observability/Phase14Metrics.cpp').read_text(encoding='utf-8')
        self.assertIn('getMatchedPathPattern()',source)
        self.assertIn('registerPostRoutingAdvice',source)
        self.assertIn('registerPreSendingAdvice',source)
        self.assertIn('getLoop()->runEvery',source)
        config=json.loads((ROOT/'config/config.phase14.json').read_text(encoding='utf-8'))
        labels={x for item in config['plugins'][0]['config']['collectors'] for x in item['labels']}
        self.assertTrue(labels <= {'flow','client','operation','outcome','method','route','status_class','stage','provider','object_kind','status','source','reason','recovery_reason'})
        self.assertNotIn('hasAvailableConnections',source)
        wrapper=(ROOT/'src/observability/Phase14Metrics.h').read_text(encoding='utf-8')
        self.assertIn('ObservationOutcome::Empty',wrapper)
        self.assertIn('ObservationOutcome::Timeout',wrapper)
        self.assertIn('throw;',wrapper)
        worker=(ROOT/'src/workers/OrderExpiryWorker.cpp').read_text(encoding='utf-8')
        self.assertIn('summary.scanned, summary.expired, summary.skipped, summary.failed',worker)

if __name__=='__main__':unittest.main(verbosity=2)
