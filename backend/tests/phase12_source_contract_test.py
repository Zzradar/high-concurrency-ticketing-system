from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class RefundContracts(unittest.TestCase):
 def test_no_webhook_binding_and_request_no_provider(self):
  worker=(ROOT/'src/services/PaymentReconciliationService.cpp').read_text(encoding='utf-8')
  wake=worker.split('wake_refunds AS')[1].split('RETURNING claimed.id')[0]
  self.assertNotIn('SET provider_refund_id',wake)
  request=(ROOT/'src/services/RefundService.cpp').read_text(encoding='utf-8')
  self.assertNotIn('createOrRecoverRefund',request)
 def test_fence_before_rights_and_sold_shape_preserved(self):
  lifecycle=(ROOT/'src/services/RefundLifecycleService.cpp').read_text(encoding='utf-8')
  fence=lifecycle.index('reconciliation_lease_token')
  self.assertLess(fence,lifecycle.index('return lockReservation(s)'))
  self.assertIn('seat.currentReservationId',lifecycle)
  order=(ROOT/'src/repositories/OrderRepository.cpp').read_text(encoding='utf-8')
  self.assertIn("SET status = 'SOLD', current_reservation_id = NULL",order)
  self.assertIn("s.status='SOLD'",order)
  self.assertIn("s.current_reservation_id IS NULL",order)
 def test_compose_real_initialization_order(self):
  for name in ['docker-compose.yml','tests/compose.phase11.yml','tests/compose.phase12.yml']:
   text=(ROOT/name).read_text(encoding='utf-8')
   targets=[line.split('/docker-entrypoint-initdb.d/')[1].split(':')[0] for line in text.splitlines() if '/docker-entrypoint-initdb.d/' in line]
   migration=next(x for x in targets if '009_add_buyer' in x)
   for target in targets:
    if 'seed' in target or 'verify' in target:self.assertLess(migration,target)
 @unittest.skipUnless((ROOT/'../performance/docker-compose.performance.yml').exists(),'Performance compose is outside the backend-only Docker build context')
 def test_performance_compose_initialization_order(self):
  text=(ROOT/'../performance/docker-compose.performance.yml').read_text(encoding='utf-8')
  targets=[line.split('/docker-entrypoint-initdb.d/')[1].split(':')[0] for line in text.splitlines() if '/docker-entrypoint-initdb.d/' in line]
  migration=next(x for x in targets if '009_add_buyer' in x)
  for target in targets:
   if 'seed' in target or 'verify' in target:self.assertLess(migration,target)
 def test_build_registers_new_sources(self):
  cmake=(ROOT/'CMakeLists.txt').read_text()
  for source in ['RefundRepository','RefundService','RefundLifecycleService','RefundController']:
   self.assertIn(source+'.cpp',cmake)
if __name__=='__main__':unittest.main(verbosity=2)
