"""Read-only Phase17 database invariant verifier, including existing transaction invariants."""
from pathlib import Path
import contextlib,io,json,os,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase17_http_test import sql
QUERIES={
 'duplicateZoneKeys':"SELECT count(*) FROM venue_zones z WHERE EXISTS(SELECT 1 FROM venue_zones o WHERE o.venue_id=z.venue_id AND o.id<>z.id AND (o.code=z.code OR o.name=z.name OR o.sort_order=z.sort_order))",
 'orphanPrices':"SELECT count(*) FROM session_zone_prices p LEFT JOIN sessions s ON s.id=p.session_id AND s.venue_id=p.venue_id LEFT JOIN venue_zones z ON z.id=p.zone_id AND z.venue_id=p.venue_id WHERE s.id IS NULL OR z.id IS NULL OR p.price<=0",
 'publishedSeatCoverage':"SELECT count(*) FROM sessions s JOIN events e ON e.id=s.event_id JOIN seats seat ON seat.venue_id=s.venue_id WHERE e.published_at IS NOT NULL AND (SELECT count(*) FROM session_seats i WHERE i.session_id=s.id AND i.seat_id=seat.id AND i.venue_id=s.venue_id)<>1",
 'invalidRoles':"SELECT count(*) FROM app_users WHERE role NOT IN ('ADMIN','CUSTOMER') OR role IS NULL",
 'orphanSeatZones':"SELECT count(*) FROM seats s LEFT JOIN venue_zones z ON z.id=s.zone_id AND z.venue_id=s.venue_id WHERE z.id IS NULL",
 'duplicateZoneSeatLabels':"SELECT count(*) FROM (SELECT zone_id,seat_label FROM seats GROUP BY 1,2 HAVING count(*)>1) q",
 'draftInventory':"SELECT count(*) FROM session_seats i JOIN sessions s ON s.id=i.session_id JOIN events e ON e.id=s.event_id WHERE s.status='DRAFT' OR e.status='DRAFT'",
 'draftAudit':"SELECT count(*) FROM events WHERE status='DRAFT' AND (published_at IS NOT NULL OR published_by IS NOT NULL)",
 'publishedAuditPair':"SELECT count(*) FROM events WHERE (published_at IS NULL)<>(published_by IS NULL)",
 'publishedSessionState':"SELECT count(*) FROM sessions s JOIN events e ON e.id=s.event_id WHERE e.published_at IS NOT NULL AND s.status='DRAFT'",
 'publishedInventoryCount':"SELECT count(*) FROM sessions s JOIN events e ON e.id=s.event_id WHERE e.published_at IS NOT NULL AND (SELECT count(*) FROM session_seats WHERE session_id=s.id)<>(SELECT count(*) FROM seats WHERE venue_id=s.venue_id)",
 'publishedPriceMismatch':"SELECT count(*) FROM session_seats i JOIN sessions s ON s.id=i.session_id JOIN events e ON e.id=s.event_id JOIN seats seat ON seat.id=i.seat_id LEFT JOIN session_zone_prices p ON p.session_id=s.id AND p.zone_id=seat.zone_id AND p.venue_id=s.venue_id WHERE e.published_at IS NOT NULL AND (p.price IS NULL OR p.price<>i.price)",
 'publishedDateRange':"SELECT count(*) FROM events e WHERE published_at IS NOT NULL AND date_range<>(SELECT to_char(min(start_time) AT TIME ZONE 'Asia/Shanghai','YYYY.MM.DD')||CASE WHEN (min(start_time) AT TIME ZONE 'Asia/Shanghai')::date=(max(start_time) AT TIME ZONE 'Asia/Shanghai')::date THEN '' ELSE ' — '||to_char(max(start_time) AT TIME ZONE 'Asia/Shanghai','YYYY.MM.DD') END FROM sessions WHERE event_id=e.id)"
}
def verify():
 checks={k:int(sql(v+';')) for k,v in QUERIES.items()}
 for line in sql((ROOT/'performance/verification/verify.sql').read_text(encoding='utf-8')).splitlines():
  name,count=line.rsplit('|',1);checks['existing:'+name]=int(count)
 os.environ['PHASE15_BASE_URL']=os.environ.get('PHASE17_BASE_URL','http://127.0.0.1:18117')
 os.environ['PHASE15_POSTGRES_CONTAINER']=os.environ.get('PHASE17_POSTGRES_CONTAINER','phase17-postgres')
 os.environ['PHASE15_REDIS_CONTAINER']=os.environ.get('PHASE17_REDIS_CONTAINER','phase17-redis')
 import phase15_verify
 phase15_verify.OUTPUT=ROOT/'performance/experiments/phase17-admin-publishing/phase15'
 with contextlib.redirect_stdout(io.StringIO()):previous=phase15_verify.verify()
 result={'passed':not any(checks.values()) and previous['passed'],'checks':checks,'phase15And16':previous}
 output=ROOT/'performance/experiments/phase17-admin-publishing';output.mkdir(parents=True,exist_ok=True);(output/'verifier.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2));return result
if __name__=='__main__':
 if not verify()['passed']:raise SystemExit(1)
