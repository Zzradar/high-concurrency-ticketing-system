"""Phase17-specific negative verifier mutations stay inside rolled-back PG transactions."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/verification'))
from phase17_verify import QUERIES,sql
class VerifierTest(unittest.TestCase):
 def check(self,name,mutation):return int(sql('BEGIN;'+mutation+';'+QUERIES[name]+';ROLLBACK;'))
 def test_draft_inventory_is_detected(self):
  self.assertGreater(self.check('draftInventory',"UPDATE events SET status='DRAFT' WHERE id=(SELECT id FROM events WHERE published_at IS NOT NULL LIMIT 1)"),0)
 def test_published_price_drift_is_detected(self):
  self.assertGreater(self.check('publishedPriceMismatch',"UPDATE session_zone_prices SET price=price+1 WHERE session_id=(SELECT s.id FROM sessions s JOIN events e ON e.id=s.event_id WHERE e.published_at IS NOT NULL LIMIT 1)"),0)
 def test_date_range_drift_is_detected(self):
  self.assertGreater(self.check('publishedDateRange',"UPDATE events SET date_range='wrong' WHERE published_at IS NOT NULL"),0)
if __name__=='__main__':unittest.main(verbosity=2)
