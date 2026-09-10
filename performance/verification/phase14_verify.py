"""Per-run reconciliation layered over the existing authoritative verify.sql."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase14_model import seat


def literal(value):return "'"+str(value).replace("'","''")+"'"
def user_scope(bounds,column='user_id'):
    a,b=bounds
    if not isinstance(a,int) or not isinstance(b,int) or not 0<=a<b:raise ValueError('invalid user scope')
    return f"{column} LIKE 'perf-user-%' AND substring({column} from '[0-9]+$')::bigint BETWEEN {a+1} AND {b}"


def count(summary,metric,step,result='business_success',scenario=None):
    return sum(x['count'] for x in summary['counts'] if x['metric']==metric and x['tags'][1]==step and x['tags'][2]==result and (scenario is None or x['tags'][0]==scenario))


def capture_temporary_owners(env,spec):
    t=spec['targets'];n=1 if spec['case']=='H3' else t['hotspot']['seats']
    targets=[seat(i,t,session_count=spec['sessionCount']) for i in range(n)]
    keys=['ticketing:seat-hold:{'+x['sessionId']+'}:'+x['sessionSeatId'] for x in targets]
    script="local rows={} for _,key in ipairs(KEYS) do table.insert(rows,{redis.call('GET',key) or '',redis.call('TTL',key)}) end return cjson.encode(rows)"
    rows=json.loads(env.compose('exec','-T','redis','redis-cli','--raw','EVAL',script,str(n),*keys).stdout)
    errors=[];evidence=[]
    for target,(value,ttl) in zip(targets,rows):
        pieces=value.rsplit('|',1)
        if len(pieces)!=2 or not pieces[1].isdigit() or ttl<=0:errors.append('missing, invalid or non-expiring Redis owner');continue
        owner,revision=pieces
        matches=int(env.sql(f"SELECT count(*) FROM checkout_sessions WHERE id={literal(owner)} AND session_id={literal(target['sessionId'])} AND {user_scope(t['slices']['main'])} AND status='SELECTING';"))
        if matches!=1:errors.append('Redis owner has no matching active main checkout')
        evidence.append({**target,'owner':owner,'revision':int(revision),'ttlSeconds':ttl,'matchingCheckout':matches})
    return {'passed':len(rows)==n and len(evidence)==n and not errors,'expectedOwners':n,'rows':evidence,'errors':errors}


def verify_run(env,spec,summary):
    t=spec['targets'];result=env.invariants();errors=[];queries={};data={}
    def query(name,sql):
        queries[name]=sql;data[name]=json.loads(env.sql(sql));return data[name]
    scope=user_scope(t['slices']['main'],'o.user_id')
    orders=query('mainOrders',f'''SELECT json_build_object('orders',count(*),'users',count(DISTINCT o.user_id),'reservations',count(DISTINCT o.reservation_id),
        'wrong_seat_count',count(*) FILTER (WHERE (SELECT count(*) FROM reservation_session_seats r WHERE r.reservation_id=o.reservation_id)<>1)) FROM orders o WHERE {scope};''')
    expected=sum(x['count'] for x in summary['counts'] if x['metric']=='phase14_results' and x['tags'][1] in ('order','reservation') and x['tags'][2]=='business_success' and (x['tags'][0]=='main' or x['tags'][0].startswith('enter_')))
    if orders['orders']!=expected or orders['users']!=orders['orders'] or orders['reservations']!=orders['orders'] or orders['wrong_seat_count']:errors.append('main order/reservation/seat count mismatch')
    checkouts=query('checkoutOwnership',f'''SELECT json_build_object('mismatch',count(*) FILTER (WHERE
        (c.reservation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM reservations r WHERE r.id=c.reservation_id AND r.user_id=c.user_id AND r.session_id=c.session_id))
        OR c.status='SUBMITTING')) FROM checkout_sessions c WHERE {user_scope(t['slices']['main'],'c.user_id')};''')
    if checkouts['mismatch']:errors.append('checkout logical ownership or unresolved commit')
    if spec['case'] in ('H1','H2','H3'):
        n=t['hotspot']['users'];winners=1 if spec['case']=='H3' else t['hotspot']['seats']
        step='reservation' if spec['path']=='formal' else 'hold'
        actual_success=count(summary,'phase14_results',step,scenario='main');actual_conflict=count(summary,'phase14_results',step,'business_conflict','main')
        if actual_success!=winners or actual_conflict!=n-winners:errors.append('hotspot exact winner/conflict count mismatch')
        if spec['path']=='formal':
            hot=query('hotspotOwners',f'''SELECT COALESCE(json_agg(row_to_json(x)),'[]') FROM (
                SELECT i.session_seat_id,count(*) AS owners FROM reservation_session_seats i JOIN reservations r ON r.id=i.reservation_id
                WHERE {user_scope(t['slices']['main'],'r.user_id')} AND r.status IN ('ACTIVE','CONFIRMED') GROUP BY i.session_seat_id) x;''')
            if len(hot)!=winners or any(x['owners']!=1 for x in hot):errors.append('hotspot database owners mismatch')
        else:
            owner_file=env.root/'temporary-owners.json'
            owners=json.loads(owner_file.read_text(encoding='utf-8')) if owner_file.exists() else {'passed':False,'errors':['missing timed Redis snapshot']}
            data['temporaryOwners']=owners
            if not owners['passed']:errors.append('temporary Redis owner reconciliation failed')
    login=query('loginSessions',f'''SELECT json_build_object('sessions',count(*),'users',count(DISTINCT user_id),'uniqueDigests',count(DISTINCT token_hash)) FROM user_sessions WHERE {user_scope(t['slices']['login'])} AND revoked_at IS NULL AND idle_expires_at>clock_timestamp() AND absolute_expires_at>clock_timestamp();''')
    login_success=count(summary,'phase14_results','login');identities=count(summary,'phase14_results','login_identity')
    if login['sessions']!=login_success or login['users']!=login_success or login['uniqueDigests']!=login_success or login_success!=identities:errors.append('login session/identity conservation failed')
    login_total=sum(x['count'] for x in summary['counts'] if x['metric']=='phase14_started' and x['tags'][1]=='login')
    if login_success+count(summary,'phase14_results','login','capacity_rejection')!=login_total:errors.append('login success + AUTH_BUSY != submissions')
    payments=query('paymentTerminal',f'''SELECT json_build_object('orders',count(*),'paid',count(*) FILTER(WHERE o.status='PAID' AND r.status='CONFIRMED'),
        'invalid',count(*) FILTER (WHERE
        (SELECT count(*) FROM payment_attempts a WHERE a.order_id=o.id AND a.status='SUCCEEDED' AND a.accepted_at IS NOT NULL AND a.provider='simulation' AND a.provider_payment_id IS NOT NULL)<>1
        OR EXISTS(SELECT 1 FROM payment_attempts a WHERE a.order_id=o.id AND (a.status='PROCESSING' OR a.completed_at > a.started_at + make_interval(secs=>{t['probes']['paymentDeadlineSeconds']})))
        OR EXISTS(SELECT 1 FROM reservation_session_seats i JOIN session_seats s ON s.id=i.session_seat_id WHERE i.reservation_id=r.id AND s.status<>'SOLD')))
        FROM orders o JOIN reservations r ON r.id=o.reservation_id WHERE {user_scope(t['slices']['payment'],'o.user_id')};''')
    paid=count(summary,'phase14_results','payment_terminal')
    if payments['orders']!=paid or payments['paid']!=paid or payments['invalid']:errors.append('payment terminal reconciliation failed')
    if spec['case'] in ('J1','O1','U1','U2','S1'):
        if any(x['metric']=='phase14_results' and x['tags'][2]=='business_conflict' and x['count'] for x in summary['counts']):errors.append('unexpected conflict in low-conflict pool')
    result.update(passed=result['passed'] and not errors,errors=errors,queries=queries,scoped=data)
    return result


def expiry_fixture(env,t,run_id):
    n=t['expiry']['orders'];start=t['slices']['expiry'][0];seat_start=t['seatSlices']['expiry'][0]
    pairs=[(start+i+1,seat(seat_start+i,t)) for i in range(n)]
    rows=','.join(f"({i},{literal(x['sessionId'])},{literal(x['sessionSeatId'])})" for i,x in pairs)
    namespace=literal(run_id)
    sql=f'''BEGIN;
    CREATE TEMP TABLE phase14_expiry_input ON COMMIT DROP AS
      SELECT x.*, 'perf-user-'||lpad(x.i::text,GREATEST(6,length(x.i::text)),'0') AS uid,
        {namespace}||'-r-'||x.i AS rid,{namespace}||'-o-'||x.i AS oid,
        transaction_timestamp() AS created, transaction_timestamp()+make_interval(secs=>{t['expiry']['futureSeconds']}) AS expiry
      FROM (VALUES {rows}) AS x(i,session_id,seat_id);
    INSERT INTO reservations(id,user_id,session_id,status,created_at,expires_at,idempotency_key)
      SELECT rid,uid,session_id,'ACTIVE',created,expiry,rid FROM phase14_expiry_input;
    INSERT INTO reservation_session_seats(reservation_id,session_id,session_seat_id,reserved_price)
      SELECT x.rid,x.session_id,x.seat_id,s.price FROM phase14_expiry_input x JOIN session_seats s ON s.id=x.seat_id;
    UPDATE session_seats s SET status='HELD',current_reservation_id=x.rid FROM phase14_expiry_input x WHERE s.id=x.seat_id AND s.status='AVAILABLE';
    INSERT INTO orders(id,user_id,reservation_id,status,total_amount,created_at,expires_at)
      SELECT x.oid,x.uid,x.rid,'PENDING_PAYMENT',s.price,x.created,x.expiry FROM phase14_expiry_input x JOIN session_seats s ON s.id=x.seat_id;
    INSERT INTO user_notifications(id,user_id,order_id,type,title,message,dedupe_key,created_at)
      SELECT oid||'-created',uid,oid,'ORDER_CREATED','订单已创建','订单已创建，请在有效期内完成支付。','order-created:'||oid,created FROM phase14_expiry_input;
    COMMIT;'''
    env.sql(sql)
    result=env.invariants()
    if not result['passed']:raise RuntimeError('E1 fixture violated invariants')
    return result
