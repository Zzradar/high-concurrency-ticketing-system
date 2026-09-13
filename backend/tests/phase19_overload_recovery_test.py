"""Bounded ENFORCED recovery regression on a fresh Phase19 Fake-Provider fixture.
This is a capability test, not a capacity benchmark or the polling A/B protocol.
"""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import unittest
import uuid


def summarize(rows):
    counts = {}
    for row in rows:
        key = str(row['status']) + ':' + str(row.get('code', ''))
        counts[key] = counts.get(key, 0) + 1
    return {'count':len(rows),'outcomes':counts,'maxMilliseconds':max((r['milliseconds'] for r in rows),default=0)}


def main():
    project = os.environ.get('COMPOSE_PROJECT_NAME', '')
    if not project.startswith('phase19-') or 'phase12' not in os.environ.get('COMPOSE_FILE',''):
        raise RuntimeError('Requires a fresh Phase19-owned financial capability fixture')
    os.environ.update(PHASE18_BASE_URL=os.environ['TICKETING_BASE_URL'],
        PHASE18_POSTGRES_CONTAINER=project+'-postgres-1', PHASE18_REDIS_CONTAINER=project+'-redis-1')
    import phase18_admission_http_test as admission
    from phase11_stripe_integration_test import fake, payment_for_attempt, signed_webhook

    def sql(statement):
        result = subprocess.run(['docker','compose','exec','-T','postgres','psql','-U','ticketing','-d','ticketing','-qAt','-F','\t','-v','ON_ERROR_STOP=1'],
            input=statement,text=True,encoding='utf-8',capture_output=True)
        if result.returncode:raise AssertionError('Isolated SQL failed: '+result.stderr[-500:])
        return result.stdout.strip()
    admission.sql = sql
    output = Path(os.environ['PHASE18_FINANCIAL_OUT'])/'overload-recovery.json'
    if output.exists():raise RuntimeError('Refuse replacing recovery evidence')
    record = {'startedUtc':datetime.now(timezone.utc).isoformat(),'scriptSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'kind':'bounded functional ENFORCED flood; no throughput or SLA claim','provider':'local Fake Stripe only',
        'floodLimits':{'workers':4,'seconds':4,'maxRequestsPerWorker':300,'minimumPauseSeconds':.01},'phases':[],'passed':False}

    class Recovery(unittest.TestCase):
        def test_existing_checkout_order_payment_refund_remain_recoverable(self):
            case = admission.AdmissionHTTP();case.setUp()
            self.assertEqual(sql("SELECT count(*) FROM session_seats WHERE session_id='"+case.s+"' AND status='AVAILABLE'"),'2')
            record['beforeVerifier']={'newFixtureSeats':2,'sqlAvailable':2}
            fake('/__admin__/reset', {});fake('/__admin__/configure', {'paymentMode':'processing','refundMode':'pending'})
            status,checkout,_ = case.u.request('/checkout-sessions',method='POST',body={'sessionId':case.s,'seatIds':[case.seats[0]['id']]})
            self.assertEqual(status,201)
            status,reservation,_ = case.u.request('/reservations',method='POST',body={'sessionId':case.s,'seatIds':[case.seats[1]['id']]},headers={'Idempotency-Key':'phase19-recovery-'+uuid.uuid4().hex})
            self.assertEqual(status,201)
            order=reservation['order']['id']
            status,payment,_ = case.u.request('/orders/'+order+'/pay',method='POST')
            self.assertEqual(status,202);attempt=payment['paymentAttempt']['id']
            provider=admission.until(lambda:payment_for_attempt(attempt))
            policy=case.policy('ENFORCED')
            admission.until(lambda:case.current().get('state')=='NOT_JOINED')
            record['policy']={'mode':'ENFORCED','maxActiveUsers':1,'localBulkhead':'production defaults retained','version':policy['policyVersion']}
            stop=threading.Event()

            def wave(name, refund=None):
                rows=[];reads=[];lock=threading.Lock();began=time.perf_counter();deadline=began+4
                record['phases'].append({'name':name,'floodTimeline':rows,'recoveryTimeline':reads})
                def writer(worker):
                    for ordinal in range(300):
                        if stop.is_set() or time.perf_counter()>=deadline:return
                        started=time.perf_counter()
                        status,body,headers=case.u.request('/checkout-sessions',method='POST',body={'sessionId':case.s,'seatIds':[case.seats[0]['id']]},timeout=10)
                        row={'worker':worker,'ordinal':ordinal,'status':status,'code':body.get('code'),
                            'startedMs':(started-began)*1000,'milliseconds':(time.perf_counter()-started)*1000,
                            'retryAfterHeader':headers.get('Retry-After',headers.get('retry-after')),'retryAfterMs':body.get('retryAfterMs')}
                        with lock:rows.append(row)
                        time.sleep(.01)
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    futures=[pool.submit(writer,n) for n in range(4)]
                    admission.until(lambda:len(rows)>=8,seconds=3)
                    paths=[('checkout','/checkout-sessions/'+checkout['id']),('order','/orders/'+order),('payment','/payment-attempts/'+attempt)]
                    if refund:paths.append(('refund','/refunds/'+refund))
                    try:
                        for _ in range(5):
                            for family,path in paths:
                                started=time.perf_counter();status,body,_=case.u.request(path,timeout=10)
                                reads.append({'family':family,'status':status,'businessStatus':body.get('status'),'startedMs':(started-began)*1000,'milliseconds':(time.perf_counter()-started)*1000})
                                self.assertEqual(status,200,family)
                                if family=='payment' and not refund:self.assertEqual(body['status'],'PROCESSING')
                                if family=='refund':self.assertEqual(body['status'],'PROCESSING')
                            time.sleep(.05)
                    finally:
                        for future in futures:future.result(timeout=15)
                self.assertGreaterEqual(len(rows),8)
                self.assertTrue(all((r['status'],r['code']) in [(409,'ADMISSION_REQUIRED'),(429,'RATE_LIMITED')] for r in rows),summarize(rows))
                self.assertTrue(all(r['startedMs']<4000 for r in reads),'Recovery reads must begin during the flood')
                self.assertLess(max(r['startedMs'] for r in reads),max(r['startedMs'] for r in rows),'Actual new-purchase traffic must overlap all recovery reads')
                for row in rows:
                    if row['status']==429:
                        self.assertGreater(int(row['retryAfterHeader'] or 0),0)
                        self.assertGreater(row['retryAfterMs'] or 0,0)


            try:
                wave('processing-payment')
                fake('/__admin__/configure',{'paymentId':provider['id'],'paymentStatus':'succeeded'})
                provider=payment_for_attempt(attempt)
                self.assertEqual(signed_webhook('phase19-overload-'+uuid.uuid4().hex,'payment_intent.succeeded',provider)[0],200)
                admission.until(lambda:sql("SELECT status FROM orders WHERE id='"+order+"'")=='PAID')
                status,value,_=case.u.request('/orders/'+order+'/refunds',method='POST')
                self.assertEqual(status,202);refund=value['refund']['id']
                remote=admission.until(lambda:next((r for r in fake('/__admin__/state')['refunds'] if r['metadata']['local_refund_id']==refund),None))
                wave('processing-refund',refund)
                fake('/__admin__/configure',{'refundId':remote['id'],'refundStatus':'succeeded'})
                sql("UPDATE refunds SET next_reconcile_at=clock_timestamp() WHERE id='"+refund+"'")
                admission.until(lambda:sql("SELECT status FROM refunds WHERE id='"+refund+"'")=='SUCCEEDED')
                self.assertEqual(case.u.request('/checkout-sessions/'+checkout['id']+'/abandon',method='POST')[0],200)
                case.policy('OFF');admission.until(lambda:case.current().get('state')=='NOT_REQUIRED')
                # Exact fixture ownership/amount convergence, plus the unchanged global SQL verifier.
                self.assertEqual(sql("SELECT count(*) FROM session_seats WHERE session_id='"+case.s+"' AND status<>'AVAILABLE'"),'0')
                self.assertEqual(sql("SELECT f.status||'|'||o.status||'|'||r.status||'|'||(f.amount=o.total_amount)::text FROM refunds f JOIN orders o ON o.id=f.order_id JOIN reservations r ON r.id=o.reservation_id WHERE f.id='"+refund+"'"),'SUCCEEDED|CANCELLED|CANCELLED|true')
                admission.until(lambda:sql('SELECT count(*) FROM seat_availability_outbox')=='0')
                status,body,_=case.u.request('/sessions/'+case.s+'/seat-availability?zone=A')
                self.assertEqual(status,200);self.assertFalse(body.get('degraded'))
                self.assertTrue(all(seat['status']=='AVAILABLE' for seat in body['seats']))
                root=Path(__file__).resolve().parents[2]
                checks={line.split('\t')[0]:int(line.split('\t')[1]) for line in sql((root/'performance/verification/verify.sql').read_text()).splitlines()}
                self.assertFalse(any(checks.values()),checks)
                record['verifier']={'unchangedVerifierChecks':checks,'scope':'verify.sql existing selectors plus the explicit new fixture assertions','fixtureSeatsAvailable':2,'formalOwnerAndAmountConsistent':True,'outboxDrained':True,'redisMatchesSql':True}
            finally:
                stop.set()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Recovery))
    record['passed']=result.wasSuccessful();record['endedUtc']=datetime.now(timezone.utc).isoformat()
    for phase in record['phases']:
        phase['flood']=summarize(phase['floodTimeline']);phase['recovery']=summarize(phase['recoveryTimeline'])
    output.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':record['passed'],'phaseCounts':[{p['name']:p['flood']['count']} for p in record['phases']]}))
    return 0 if record['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
