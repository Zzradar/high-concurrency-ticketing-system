"""Separate 10000-seat shape check; never changes the 5000-seat capacity fixture."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
from urllib.parse import urlencode

from seed import generator, HERE
from harness import Stack, request, save, sha


def large_profile():
    profile=json.loads((HERE/'profile.json').read_text())
    profile.update(registeredUsers=1,activeAuthSessions=1,sessionsPerEvent=1)
    profile['seatLayout']['rows']=100
    for zone in profile['priceZones']:zone['rows']=20
    return profile


def main(args):
    if args.out.exists():raise ValueError('Refuse overwriting layout evidence')
    stack=Stack(args.private)
    if stack.sql("SELECT count(*) FROM sessions WHERE id LIKE 'phase19-layout10k-%'")!='0':
        raise ValueError('Use a fresh Phase19 topology for the 10000-seat fixture')
    save(args.out/'identity.json', {'startedUtc':datetime.now(timezone.utc).isoformat(),
        'diagnostic':args.diagnostic,'stack':stack.config,'runtimeConfigSha256':sha(stack.private/'api-config.json'),
        'protocolSha256':{p.name:sha(p) for p in HERE.iterdir() if p.is_file()}})
    before=stack.verify();save(args.out/'verifier-before.json',before)
    if not before['passed']:raise RuntimeError('Pre-layout invariants')
    profile=large_profile()
    shape=generator.validate_profile(profile)
    statement=generator.build_generation_sql(profile,shape,generator.generate_session_credentials(1),86400,604800).replace('perf-','phase19-layout10k-')
    stack.sql(statement)
    stack.sql("""INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price)
SELECT s.id,z.id,z.venue_id,10000 FROM sessions s JOIN venue_zones z ON z.venue_id=s.venue_id
WHERE s.id LIKE 'phase19-layout10k-session-%';
UPDATE events SET published_at=clock_timestamp(),published_by='U-ADMIN-DEMO' WHERE id LIKE 'phase19-layout10k-event-%';""")
    session='phase19-layout10k-session-001-001'
    result={'diagnostic':args.diagnostic,'seats':shape.seats,'sessions':shape.sessions,'layout':[],'availability':[],'passed':False}
    for _ in range(5):
        code,body,timing=request(stack.base,'/sessions/'+session+'/seat-layout')
        result['layout'].append({'status':code,'count':len(body.get('seats',[])),**timing})
        if code!=200 or len(body['seats'])!=10000 or len({s['id'] for s in body['seats']})!=10000:raise RuntimeError('10000-seat layout shape')
    found={}
    for zone in [z['name'] for z in profile['priceZones']]:
        code,body,timing=request(stack.base,'/sessions/'+session+'/seat-availability?'+urlencode({'zone':zone}))
        if code!=200 or body.get('degraded') or body['mode']!='snapshot':raise RuntimeError('10000-seat snapshot')
        found.update({s['id']:s['status'] for s in body['seats']})
        result['availability'].append({'status':code,'mode':body['mode'],'zone':zone,'seats':len(body['seats']),**timing})
        code,delta,timing=request(stack.base,'/sessions/'+session+'/seat-availability?'+urlencode({'zone':zone,'generation':body['generation'],'since':body['cursor']}))
        if code!=200 or delta['mode']!='delta' or delta['changes']:raise RuntimeError('10000-seat empty Delta')
        result['availability'].append({'status':code,'mode':delta['mode'],'zone':zone,'changes':len(delta['changes']),**timing})
    expected=dict(line.split('\t') for line in stack.sql("SELECT id,status FROM session_seats WHERE session_id='"+session+"'").splitlines())
    result['mismatches']=sum(found.get(k)!=v for k,v in expected.items())+len(found.keys()-expected.keys())
    result['passed']=len(expected)==10000 and result['mismatches']==0
    result['inventorySha256']=hashlib.sha256(json.dumps(sorted(expected.items())).encode()).hexdigest()
    after=stack.verify();save(args.out/'verifier-after.json',after)
    result['passed']=result['passed'] and after['passed']
    result['endedUtc']=datetime.now(timezone.utc).isoformat()
    save(args.out/'result.json',result)
    print({'passed':result['passed'],'seats':len(expected),'mismatches':result['mismatches']})
    return 0 if result['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--diagnostic',action='store_true')
    args=parser.parse_args()
    if not args.diagnostic:
        from harness import sha
        if json.loads((HERE.parent/'protocol-sha256.json').read_text())['files']!={p.name:sha(p) for p in HERE.iterdir() if p.is_file()}:
            raise ValueError('Formal protocol drift')
    raise SystemExit(main(args))
