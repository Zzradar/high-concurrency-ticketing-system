"""Phase15 cross-table checks plus unchanged Phase16/original verifier."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase15_test_support import sql,redis,until
import phase16_verify
OUTPUT=ROOT/'performance/experiments/phase15-sales-window'
def verify():
    phase16_verify.sql=sql;phase16_verify.redis=redis;phase16_verify.until=until
    phase16_verify.BASE='http://127.0.0.1:18095';phase16_verify.OUTPUT=OUTPUT/'phase16-regression'
    previous=phase16_verify.verify()
    checks={}
    queries={
      'invalidEventWindow':"SELECT count(*) FROM events WHERE sales_starts_at IS NULL OR sales_ends_at IS NULL OR sales_starts_at>=sales_ends_at;",
      'checkoutActiveKeyMismatch':"SELECT count(*) FROM checkout_sessions WHERE (status IN ('SUBMITTING','RESERVED'))<>(active_confirm_idempotency_key IS NOT NULL);",
      'checkoutResultMismatch':"SELECT count(*) FROM checkout_sessions c JOIN reservations r ON r.id=c.reservation_id WHERE c.user_id<>r.user_id OR c.session_id<>r.session_id OR c.status<>'RESERVED';",
      'phase15DuplicateKeys':"SELECT count(*) FROM (SELECT user_id,idempotency_key FROM reservations WHERE user_id LIKE 'p15-%' GROUP BY 1,2 HAVING count(*)>1) d;",
      'phase15MissingOrder':"SELECT count(*) FROM reservations r WHERE user_id LIKE 'p15-%' AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.reservation_id=r.id);",
      'phase15OverlappingRights':"SELECT count(*) FROM (SELECT i.session_seat_id FROM reservation_session_seats i JOIN reservations r ON r.id=i.reservation_id WHERE r.status IN ('ACTIVE','CONFIRMED') GROUP BY 1 HAVING count(*)>1) d;",
      'phase15WrongAmount':"SELECT count(*) FROM orders o JOIN reservations r ON r.id=o.reservation_id WHERE o.user_id LIKE 'p15-%' AND o.total_amount<>(SELECT sum(reserved_price) FROM reservation_session_seats i WHERE i.reservation_id=r.id);",
      'phase15InventoryPointerMismatch':"SELECT count(*) FROM session_seats s JOIN reservations r ON r.id=s.current_reservation_id WHERE r.user_id LIKE 'p15-%' AND (s.status<>'HELD' OR r.status<>'ACTIVE');",
    }
    for name,query in queries.items():checks[name]=int(sql(query))
    result={'passed':previous['passed'] and not any(checks.values()),'phase15':checks,'phase16AndOriginal':previous}
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/'verifier.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2));return result
if __name__=='__main__':
    if not verify()['passed']:raise SystemExit(1)
