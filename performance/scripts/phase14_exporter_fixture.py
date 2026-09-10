"""Real PostgreSQL wait/lock fixtures with bounded, owned connections only."""
import json
import subprocess
import time
from datetime import datetime,timezone
from run_phase14 import Environment,ROOT,RESULTS,COMPOSE,load_targets,write

class Connection:
    def __init__(self,env,application):
        self.env=env;self.application=application
        self.process=subprocess.Popen(['docker','compose','-p',env.project,'-f',str(COMPOSE),
            'exec','-T','-e','PGAPPNAME='+application,'postgres','psql','-U','ticketing','-d','ticketing','-At'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env.env,cwd=ROOT)
        self.send("SET statement_timeout='20s'; SELECT pg_backend_pid();")
        line=self.process.stdout.readline()
        while not line.strip().isdigit():
            if not line:raise RuntimeError('fixture connection did not start')
            line=self.process.stdout.readline()
        self.pid=int(line);self.birth=env.sql(f"SELECT backend_start::text FROM pg_stat_activity WHERE pid={self.pid};")
    def send(self,sql):self.process.stdin.write(sql+'\n');self.process.stdin.flush()
    def close(self):
        # Cancel only this fixture's exact PID, start time and application identity.
        self.env.sql(f"SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE pid={self.pid} AND backend_start='{self.birth}' AND application_name='{self.application}';")
        self.send(r'ROLLBACK; \q')
        self.process.communicate(timeout=25)

def wait_state(env,connection,state,wait=None):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        row=json.loads(env.sql(f"SELECT row_to_json(x) FROM (SELECT state,wait_event,wait_event_type,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE pid={connection.pid}) x;"))
        if row['state']==state and (wait is None or row['wait_event']==wait):return row
        time.sleep(.1)
    raise AssertionError('fixture did not reach expected PostgreSQL state')

def metric(raw,name,**labels):
    values=[]
    for line in raw.splitlines():
        if line.startswith(name+'{') or line.startswith(name+' '):
            if all(k+'="'+v+'"' in line for k,v in labels.items()):values.append(float(line.rsplit(' ',1)[1]))
    return sum(values)

def main():
    root=RESULTS/('phase14-exporter-fixture-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    env=Environment(load_targets(smoke=True),root);env.validate();connections=[];checks=[]
    def connect(app='ticketing_backend_phase14'):
        c=Connection(env,app);connections.append(c);return c
    def scrape(name):
        raw=env.compose('exec','-T','backend','curl','--fail','--silent','http://postgres-exporter:9187/metrics').stdout.decode()
        (root/(name+'.prom')).write_text(raw,encoding='utf-8');return raw
    def check(name,passed,**evidence):
        checks.append({'name':name,'passed':bool(passed),**evidence});write(root/'checks.json',checks)
        if not passed:raise AssertionError(name)
    try:
        idle=connect();row=wait_state(env,idle,'idle','ClientRead');raw=scrape('idle')
        check('idle ClientRead excluded',metric(raw,'pg_backend_activity_waiting',state='idle')==0,state=row)
        monitored=connect('phase14_sampler');monitored.send('SELECT pg_sleep(20);');wait_state(env,monitored,'active','PgSleep')
        raw=scrape('monitor');check('monitor excluded',metric(raw,'pg_backend_activity_waiting',state='active')==0)
        sleeper=connect();sleeper.send('SELECT pg_sleep(20);');row=wait_state(env,sleeper,'active','PgSleep');raw=scrape('active')
        check('real active wait counted',metric(raw,'pg_backend_activity_waiting',state='active')>=1,state=row)
        holder=connect();holder.send('BEGIN; SELECT pg_advisory_xact_lock(14140001);');row=wait_state(env,holder,'idle in transaction')
        raw=scrape('idle-transaction');check('idle transaction separate',metric(raw,'pg_idle_transactions_idle')>=1,state=row)
        waiter=connect();waiter.send('BEGIN; SELECT pg_advisory_xact_lock(14140001);');row=wait_state(env,waiter,'active','advisory');raw=scrape('lock')
        check('ungranted lock and blocker chain',metric(raw,'pg_lock_summary_waiting')>=1 and holder.pid in row['blockers'],state=row)
        aborted=connect();aborted.send('BEGIN; SELECT 1/0;');row=wait_state(env,aborted,'idle in transaction (aborted)');raw=scrape('aborted')
        check('aborted transaction separate',metric(raw,'pg_idle_transactions_aborted')>=1,state=row)
    finally:
        for c in reversed(connections):c.close()
        raw=scrape('after');remaining=env.sql('SELECT count(*) FROM pg_stat_activity WHERE pid IN ('+','.join(str(c.pid) for c in connections)+');')
        write(root/'cleanup.json',{'remainingFixtureConnections':int(remaining)})
    print(json.dumps({'root':str(root),'passed':all(x['passed'] for x in checks),'checks':len(checks)}))
    return 0
if __name__=='__main__':raise SystemExit(main())
