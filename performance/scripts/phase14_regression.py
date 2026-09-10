"""Run existing simulation integration assertions in the dedicated Phase14 fixture.
The legacy Redis replacement fixture becomes stop/start on Phase14 tmpfs; no deletion.
"""
import copy
import importlib
import json
import os
import re
from pathlib import Path
import sys
import time
import unittest
from datetime import datetime,timezone
from run_phase14 import Environment,ROOT,RESULTS,COMPOSE,write,load_targets

MODULES=['http_integration_test','reservation_http_integration_test','checkout_session_http_integration_test',
    'seat_hold_integration_test','phase4_http_integration_test','order_expiry_integration_test',
    'payment_integration_test','order_lifecycle_integration_test','phase9_auth_http_integration_test',
    'phase9_multiclient_integration_test']

class RedisFixture:
    def __init__(self,env):self.env=env;self.stopped=False
    def __call__(self,*args):
        if args==('kill','redis'):
            self.env.compose('stop','redis');self.stopped=True;return ''
        if args==('rm','-f','redis'):
            if not self.stopped:raise ValueError('unexpected legacy replacement sequence')
            # /data is tmpfs: stopping discarded state, so retain the exact container.
            write(self.env.root/'redis-fixture-adaptation.json',{'legacy':['kill','rm','up'],
                'executed':['stop','start'],'reason':'retain container and volumes; tmpfs loses soft state',
                'businessAssertionsUnchanged':True})
            return ''
        if args==('up','-d','redis') and self.stopped:
            self.stopped=False;return self.env.compose('start','redis').stdout.decode()
        if args[:2] in [('start','redis'),('stop','redis')] or args[:4]==('exec','-T','redis','redis-cli'):
            return self.env.compose(*args).stdout.decode('utf-8').strip()
        raise ValueError('unexpected integration container operation: '+repr(args[:4]))

def failure_service(model,port):
    service=copy.deepcopy(model['services']['backend'])
    if service['environment']['TICKETING_PAYMENT_PROVIDER']!='simulation':raise ValueError('simulation required')
    service['environment']['TICKETING_PAYMENT_FORCE_OUTCOME']='FAILURE'
    service['ports']=[{'target':8080,'published':str(port),'host_ip':'127.0.0.1','protocol':'tcp'}]
    return {'services':{'backend-failure':service}}

def run_failure():
    root=RESULTS/('phase14-payment-failure-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    env=Environment(load_targets(smoke=True),root);model=env.validate();port=env.t['environment']['localPort']+1
    override=root/'failure-compose.json';write(override,failure_service(model,port))
    os.environ.update(TICKETING_BASE_URL=f'http://127.0.0.1:{port}',TICKETING_TEST_ORIGIN='http://performance.local')
    env.compose('stop','backend')
    def fixture(*args):return env.command(['docker','compose','-p',env.project,'-f',str(COMPOSE),'-f',str(override.resolve()),*args])
    try:
        fixture('up','-d','--wait','backend-failure')
        sys.path.insert(0,str(ROOT/'backend/tests'));module=importlib.import_module('payment_failure_integration_test')
        module.psql=env.sql;sys.modules['payment_integration_test'].psql=env.sql
        started=time.monotonic()
        with (root/'test.log').open('w',encoding='utf-8') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        write(root/'result.json',{'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'seconds':time.monotonic()-started,'provider':'simulation','forcedOutcome':'FAILURE','assertionsUnchanged':True})
        return 0 if result.wasSuccessful() else 1
    finally:
        fixture('stop','backend-failure');env.compose('start','backend');write(root/'correctness.json',env.invariants())


def check_live_metrics(raw):
    from phase14_exporter_fixture import metric
    allowed={'flow':{'auth','seat_read','checkout','reservation','order','payment_control','refund','other'},
        'client':{'seat_holds','auth_sessions'},'operation':{'hold_write','hold_read','auth_read','auth_write','auth_delete','login_check','login_failure','login_clear'},
        'outcome':{'success','empty','error','timeout','abandoned','scanned','expired','skipped','failed'}}
    prefixes=('ticketing_flow_requests','ticketing_db_transaction_acquire','ticketing_redis_operation','ticketing_main_event_loop','ticketing_order_expiry')
    bad=[];zero=[]
    for line in raw.splitlines():
        if not line.startswith(prefixes):continue
        for key,value in re.findall(r'(\w+)="([^"\n]*)"',line):
            if key=='le':
                try:float(value)
                except ValueError:bad.append([key,value])
            elif key not in allowed or value not in allowed[key]:bad.append([key,value])
        if line.split('{')[0].split(' ')[0].endswith('_in_flight') and float(line.rsplit(' ',1)[1])!=0:zero.append(line)
    sampled={flow:metric(raw,'ticketing_flow_requests_in_flight_high_water',flow=flow)>0 for flow in ('auth','seat_read','checkout','reservation')}
    sampled.update({op:metric(raw,'ticketing_redis_operation_duration_seconds_count',operation=op)>0 for op in ('hold_write','hold_read','auth_read','auth_write','login_check','login_failure')})
    sampled['expiry']=metric(raw,'ticketing_order_expiry_round_duration_seconds_count')>0 and metric(raw,'ticketing_order_expiry_items_total',outcome='expired')>0
    sampled['transaction']=metric(raw,'ticketing_db_transaction_acquire_duration_seconds_count')>0
    return {'passed':not bad and not zero and all(sampled.values()),'invalidLabels':bad,'nonzeroInflight':zero,'sampled':sampled}


def main():
    root=RESULTS/('phase14-regression-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    env=Environment(load_targets(smoke=True),root);env.reset(yes=True,snapshot=env.data/'base.dump')
    env.sql('TRUNCATE venues,app_users CASCADE;')
    env.sql((ROOT/'backend/db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
    os.environ.update(COMPOSE_FILE=str(ROOT/'performance/docker-compose.phase14.yml'),COMPOSE_PROJECT_NAME=env.project,
        PHASE14_DATA_ROOT=str(env.data.resolve()),TICKETING_BASE_URL=env.base,TICKETING_TEST_ORIGIN='http://performance.local')
    sys.path.insert(0,str(ROOT/'backend/tests'))
    loaded=[importlib.import_module(name) for name in MODULES]
    metrics_only='--metrics-only' in sys.argv
    if metrics_only:
        from phase14_sampling import metrics
        (root/'metrics-before.prom').write_text(metrics(env)[1],encoding='utf-8')
    fixture=RedisFixture(env)
    for module in list(sys.modules.values()):
        location=getattr(module,'__file__',None)
        if location and Path(location).resolve().parent==ROOT/'backend/tests':
            if hasattr(module,'psql'):module.psql=env.sql
            if hasattr(module,'compose'):module.compose=fixture
            if hasattr(module,'redis_cli'):module.redis_cli=lambda *a:fixture('exec','-T','redis','redis-cli','--raw',*a)
    records=[]
    selected={'checkout_session_http_integration_test':'CheckoutSessionHttpIntegrationTest.test_create_get_list_replace_empty_and_abandon',
        'reservation_http_integration_test':'ReservationHttpIntegrationTest.test_basic_success_and_database_invariants',
        'seat_hold_integration_test':'SeatHoldIntegrationTest.test_seat_map_masks_other_hold_but_not_owner_and_expires',
        'phase9_auth_http_integration_test':'Phase9AuthHttpIntegrationTest.test_login_cookie_me_and_invalid_credentials',
        'order_expiry_integration_test':'OrderExpiryIntegrationTest.test_expiry_is_atomic_and_preserves_history'}
    for module in loaded:
        if metrics_only and module.__name__ not in selected:continue
        start=time.monotonic()
        with (root/(module.__name__+'.log')).open('w',encoding='utf-8') as log:
            suite=unittest.defaultTestLoader.loadTestsFromName(selected[module.__name__],module) if metrics_only else unittest.defaultTestLoader.loadTestsFromModule(module)
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        row={'module':module.__name__,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'skipped':len(result.skipped),'seconds':time.monotonic()-start}
        records.append(row);write(root/'regressions.json',records);print(json.dumps(row),flush=True)
        if not result.wasSuccessful():return 1
    write(root/'correctness.json',env.invariants())
    if metrics_only:
        time.sleep(1);raw=metrics(env)[1];(root/'metrics-after.prom').write_text(raw,encoding='utf-8')
        checks=check_live_metrics(raw);write(root/'live-metrics-checks.json',checks)
        if not checks['passed']:return 1
    return 0

if __name__=='__main__':raise SystemExit(run_failure() if '--failure-only' in sys.argv else main())
