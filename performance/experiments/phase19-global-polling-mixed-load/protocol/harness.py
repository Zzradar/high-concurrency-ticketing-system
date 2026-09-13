"""Fresh Phase19 SUT topology and read-only evidence collection. No legacy resources are addressed."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError

from seed import seed, ROOT
from calibrate import sample

HERE = Path(__file__).resolve().parent
OPENER = build_opener(ProxyHandler({}))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args, stdin=None, timeout=120):
    p = subprocess.run(list(map(str,args)), input=stdin, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if p.returncode:
        raise RuntimeError(str(args[:3])+': '+p.stderr[-1800:])
    return p.stdout.strip()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def request(base, path, user=None, method='GET', body=None):
    headers = {'Accept':'application/json','Content-Type':'application/json','Origin':'http://performance.local'}
    if user:
        headers.update(Cookie=f"ticketing_session={user['sessionToken']}; ticketing_csrf={user['csrfToken']}", **{'X-CSRF-Token':user['csrfToken']})
    started = time.perf_counter()
    try:
        response = OPENER.open(Request(base+path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method), timeout=12)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        value = json.loads(raw) if raw else None
        return response.status, value, {'seconds':time.perf_counter()-started,'bytes':len(raw)}


class Stack:
    def __init__(self, private):
        self.private = Path(private).resolve()
        self.config = json.loads((self.private/'stack.json').read_text())
        self.prefix = self.config['prefix']
        if not re.fullmatch(r'phase19-[a-z0-9-]+', self.prefix):
            raise ValueError('Not a Phase19 topology')
        self.base = 'http://127.0.0.1:'+str(self.config['apiPort'])
        self.users = json.loads((self.private/'fixture/users.json').read_text())
        self.fixture = json.loads((self.private/'fixture/config.json').read_text())

    def sql(self, query):
        return run('docker','exec','-i',self.prefix+'-postgres','psql','-U','postgres','-d','ticketing','-qAt','-F','\t','-v','ON_ERROR_STOP=1',stdin=query)

    def redis(self, *args):
        raw = run('docker','exec',self.prefix+'-redis','redis-cli','--json',*args)
        if raw.startswith('error:'):
            raise RuntimeError(raw)
        return raw if args[0].upper() == 'INFO' else json.loads(raw)

    def verify(self):
        deadline = time.monotonic()+30
        while self.sql('SELECT count(*) FROM seat_availability_outbox') != '0' and time.monotonic()<deadline:
            time.sleep(.25)
        checks = {line.split('\t')[0]:int(line.split('\t')[1]) for line in self.sql((ROOT/'performance/verification/verify.sql').read_text().replace('perf-','phase19-')).splitlines()}
        checks['outbox_not_drained'] = int(self.sql('SELECT count(*) FROM seat_availability_outbox'))
        checks['unexplained_processing'] = int(self.sql("SELECT count(*) FROM checkout_sessions WHERE user_id LIKE 'phase19-%' AND status='SUBMITTING'"))
        mismatches = 0
        for session in [self.fixture[k] for k in ['readerSession','writerSession','hotspotSession','sentinelSession','journeySession']]:
            expected = dict(line.split('\t') for line in self.sql("SELECT id,status FROM session_seats WHERE session_id='"+session+"' ORDER BY id").splitlines())
            actual = {}
            for zone in self.fixture['zones']:
                from urllib.parse import urlencode
                code, body, _ = request(self.base, '/sessions/'+session+'/seat-availability?'+urlencode({'zone':zone}))
                if code != 200 or body.get('degraded'):
                    raise RuntimeError('Verifier snapshot not authoritative')
                actual.update({s['id']:s['status'] for s in body['seats']})
            mismatches += sum(actual.get(key)!=value for key,value in expected.items())+len(actual.keys()-expected.keys())
        checks['redis_display_mismatch'] = mismatches
        return {'utc':datetime.now(timezone.utc).isoformat(),'passed':not any(checks.values()),'checks':checks}

    def observation(self):
        pg = self.sql("""SELECT json_build_object(
          'database',(SELECT row_to_json(x) FROM (SELECT xact_commit,xact_rollback,deadlocks,blks_read,blks_hit,temp_bytes FROM pg_stat_database WHERE datname=current_database()) x),
          'activity',(SELECT coalesce(json_agg(x),'[]') FROM (SELECT state,wait_event_type,wait_event,count(*) FROM pg_stat_activity WHERE datname=current_database() GROUP BY 1,2,3) x),
          'waitingLocks',(SELECT count(*) FROM pg_locks WHERE NOT granted),
          'statements',(SELECT coalesce(json_agg(x),'[]') FROM (SELECT queryid,calls,rows,total_exec_time,mean_exec_time FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 40) x))""")
        with OPENER.open(self.base+'/metrics',timeout=5) as response:
            metrics = response.read().decode()
        return {'utc':datetime.now(timezone.utc).isoformat(),'postgres':json.loads(pg),
            'redis':{section:self.redis('INFO',section) for section in ['memory','clients','stats','commandstats']},
            'backendMetrics':metrics}


def setup(args):
    private = args.private.resolve()
    if private.exists():
        raise ValueError('Use a fresh private directory')
    if not re.fullmatch(r'phase19-[a-z0-9-]+',args.prefix):
        raise ValueError('Invalid Phase19 prefix')
    private.mkdir(parents=True)
    tags = {'api':'phase14-engineering-build:20260910-v3','postgres':'postgres:16-alpine','redis':'redis:7.4-alpine','frontend':'nginx:1.28-alpine','k6':'grafana/k6:2.2.0'}
    images = {role:json.loads(run('docker','image','inspect',tag))[0] for role,tag in tags.items()}
    stack = {'prefix':args.prefix,'apiPort':args.api_port,'frontendPort':args.frontend_port,
        'baseCommit':'2c680e78d532eace9e7f28862e7efb6ef2bdf4fb','binarySha256':sha(args.binary),
        'images':{role:{'id':obj['Id'],'digests':obj['RepoDigests']} for role,obj in images.items()},
        'bulkheadCondition':'event policies OFF; process-local Bulkheads at production defaults',
        'sourceCommit':run('git','-C',ROOT,'rev-parse','HEAD')}
    save(private/'stack.json',stack)
    for network in ['data','ingress']:
        run('docker','network','create',*(['--internal'] if network=='data' else []),args.prefix+'-'+network)
    volume = args.prefix+'-postgres-data'
    if volume in run('docker','volume','ls','--format','{{.Name}}').splitlines():
        raise ValueError('Refuse existing volume')
    run('docker','volume','create','--label','phase19.owner='+args.prefix,volume)
    for role in ['postgres','redis']:
        extra = ['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=ticketing','--mount',f'type=volume,source={volume},target=/var/lib/postgresql/data'] if role=='postgres' else []
        command = ['-c','shared_preload_libraries=pg_stat_statements','-c','pg_stat_statements.track=all'] if role=='postgres' else []
        run('docker','run','-d','--name',args.prefix+'-'+role,'--label','phase19.owner='+args.prefix,'--network',args.prefix+'-data','--network-alias',role,
            '--cpus','1','--memory','512m','--pids-limit','128','--ulimit','nofile=4096:4096',*extra,images[role]['Id'],*command)
    def sql(query):
        return run('docker','exec','-i',args.prefix+'-postgres','psql','-U','postgres','-d','ticketing','-qAt','-F','\t','-v','ON_ERROR_STOP=1',stdin=query)
    for _ in range(100):
        try:
            sql('SELECT 1');break
        except RuntimeError:
            time.sleep(.2)
    else:
        raise RuntimeError('Postgres readiness')
    for path in sorted((ROOT/'backend/db/migrations').glob('*.sql')):
        sql(path.read_text(encoding='utf-8'))
    sql((ROOT/'backend/db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
    sql('CREATE EXTENSION pg_stat_statements')
    save(private/'fixture-manifest.json',seed(sql,private/'fixture'))
    fixture = json.loads((private/'fixture/config.json').read_text())
    fixture['holdTtlSeconds']=15
    save(private/'fixture/config.json',fixture)
    config = json.loads((ROOT/'backend/config/config.phase14.json').read_text())
    config['db_clients'][0].update(user='postgres',passwd='')
    config['custom_config']['checkout_seat_hold']['ttl_seconds']=15
    config['custom_config']['authentication']['allowed_origins'] += ['http://127.0.0.1:'+str(args.frontend_port)]
    save(private/'api-config.json',config)
    # Copy the verified binary into the private runtime, never into the evidence tree.
    (private/'ticketing_backend').write_bytes(args.binary.read_bytes())
    run('docker','run','-d','--name',args.prefix+'-api','--label','phase19.owner='+args.prefix,'--network',args.prefix+'-data','--network-alias','api',
        '--cpus','2','--memory','1g','--pids-limit','256','--ulimit','nofile=4096:4096','-p',f'127.0.0.1:{args.api_port}:8080',
        '--mount',f'type=bind,source={private},target=/runtime,readonly','--entrypoint','/runtime/ticketing_backend',images['api']['Id'],'/runtime/api-config.json')
    run('docker','network','connect',args.prefix+'-ingress',args.prefix+'-api')
    nginx = 'events { worker_connections 2048; }\nhttp { include /etc/nginx/mime.types; access_log off; server { listen 8080; root /web; location /api/ { proxy_pass http://api:8080/; } location / { try_files $uri $uri/ /index.html; } } }\n'
    (private/'nginx.conf').write_text(nginx)
    run('docker','run','-d','--name',args.prefix+'-frontend','--label','phase19.owner='+args.prefix,'--network',args.prefix+'-data',
        '--cpus','.5','--memory','128m','--pids-limit','64','--ulimit','nofile=4096:4096','-p',f'127.0.0.1:{args.frontend_port}:8080',
        '--mount',f'type=bind,source={ROOT / "frontend/dist"},target=/web,readonly','--mount',f'type=bind,source={private / "nginx.conf"},target=/etc/nginx/nginx.conf,readonly',images['frontend']['Id'])
    run('docker','network','connect',args.prefix+'-ingress',args.prefix+'-frontend')
    for _ in range(100):
        try:
            if request('http://127.0.0.1:'+str(args.api_port),'/health')[0]==200:
                break
        except OSError:
            time.sleep(.2)
    else:
        raise RuntimeError('API readiness')
    verification=Stack(private).verify()
    save(private/'initial-verifier.json',verification)
    if not verification['passed']:
        raise RuntimeError('Initial fixture invariants')
    print('Fresh Phase19 topology and fixture ready; initial verifier passed.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['setup','verify'])
    parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--prefix',default='phase19-baseline')
    parser.add_argument('--binary',type=Path)
    parser.add_argument('--api-port',type=int,default=18392)
    parser.add_argument('--frontend-port',type=int,default=18393)
    args=parser.parse_args()
    if args.action=='setup':setup(args)
    else:print(json.dumps(Stack(args.private).verify(),indent=2))
