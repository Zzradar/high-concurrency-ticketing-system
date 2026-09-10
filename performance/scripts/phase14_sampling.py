"""Dedicated-run resource sampling; observations carry actual timestamps."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
import threading
from urllib.request import build_opener,ProxyHandler
from performance_evidence import parse_redis_info


def metrics(env):
    with build_opener(ProxyHandler({})).open(env.base+'/metrics',timeout=10) as response:
        raw=response.read().decode()
    values={}
    for line in raw.splitlines():
        if line.startswith('#'):continue
        match=re.match(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+([-+eE.0-9]+)',line)
        if match:
            name,value=match.groups();value=float(value)
            values[name]=max(values.get(name,0),value) if name.endswith('_oldest_seconds') else values.get(name,0)+value
    return values,raw


def postgres(env):
    begin=time.time()
    app=env.t['environment']['applicationName']
    sql=f'''SELECT json_build_object(
    'time',extract(epoch from clock_timestamp()),
    'activeWaits',count(*) FILTER(WHERE state='active' AND wait_event IS NOT NULL),
    'lockWaits',count(*) FILTER(WHERE state='active' AND wait_event_type='Lock'),
    'idleTransaction',count(*) FILTER(WHERE state='idle in transaction'),
    'idleAborted',count(*) FILTER(WHERE state='idle in transaction (aborted)'))
    FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND application_name='{app}';'''
    value=json.loads(env.sql(sql));end=time.time()
    value['clockSkewMs']=(value['time']-(begin+end)/2)*1000
    value['clockUncertaintyMs']=(end-begin)*500
    return value


def postgres_clock_sample(env):
    # Bootstrap Docker/psql BEFORE timing SQL. CLI process launch is asymmetric
    # transport latency, not a clock offset. The frozen offset guard is unchanged.
    from phase14_pg_stream import ActivityConnection
    from types import SimpleNamespace
    connection=ActivityConnection(env)
    try:
        value=postgres(SimpleNamespace(t=env.t,sql=connection.sql))
        value['clockTransport']='established_read_only_psql'
        value['clockConnectionPid']=connection.pid
    finally:connection.close()
    value['clockConnectionClosed']=True
    return value


def pg_snapshot(env):
    return json.loads(env.sql('''SELECT json_build_object(
      'serverVersion',current_setting('server_version'),'postmasterStart',pg_postmaster_start_time(),
      'database',(SELECT row_to_json(x) FROM pg_stat_database x WHERE datname=current_database()),
      'statementsInfo',(SELECT row_to_json(x) FROM pg_stat_statements_info x),
      'statements',(SELECT COALESCE(json_agg(row_to_json(x)),'[]') FROM (SELECT queryid,calls,total_exec_time,rows,shared_blks_hit,shared_blks_read,temp_blks_written FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())) x),
      'io',(SELECT json_agg(row_to_json(x)) FROM pg_stat_io x),
      'wal',(SELECT row_to_json(x) FROM pg_stat_wal x));'''))


def pg_delta(before,after):
    errors=[]
    if before['postmasterStart']!=after['postmasterStart']:errors.append('PostgreSQL restarted')
    for key in ('database','statementsInfo','wal'):
        if before[key].get('stats_reset')!=after[key].get('stats_reset'):errors.append(key+' statistics reset')
    if after['statementsInfo'].get('dealloc',0)!=before['statementsInfo'].get('dealloc',0):errors.append('statement entries evicted')
    def differences(a,b):return {k:b[k]-v for k,v in a.items() if isinstance(v,(int,float)) and isinstance(b.get(k),(int,float))}
    def rows(key,identity):
        old={tuple(x.get(k) for k in identity):x for x in before.get(key,[]) or []}
        new={tuple(x.get(k) for k in identity):x for x in after.get(key,[]) or []}
        if old.keys()-new.keys():errors.append(key+' entries disappeared')
        result=[]
        for row_id,value in new.items():
            previous=old.get(row_id,{k:0 for k,v in value.items() if isinstance(v,(int,float))})
            if key=='io' and previous.get('stats_reset',value.get('stats_reset'))!=value.get('stats_reset'):errors.append('io statistics reset')
            delta=differences(previous,value)
            for label in identity:delta.pop(label,None)
            if any(v<0 for v in delta.values()):errors.append(key+' counter decreased')
            result.append({'identity':dict(zip(identity,row_id)),'delta':delta})
        return result
    statements=rows('statements',['queryid']);io=rows('io',['backend_type','object','context'])
    return {'valid':not errors,'errors':errors,'database':differences(before['database'],after['database']),
            'wal':differences(before['wal'],after['wal']),'statements':statements,'io':io}


class LightPostgresSampler:
    """Separate PG activity cadence, independent of slow Docker stats collection."""
    def __init__(self,env,interval,*,read=None):
        if interval<=0:raise ValueError('invalid sampling interval')
        self.env=env;self.interval=interval;self.read=read;self.done=threading.Event();self.samples=[];self.errors=[]
        self.thread=threading.Thread(target=self._run,name='phase14-pg-activity',daemon=True)
    def start(self):self.thread.start();return self
    def _run(self):
        path=self.env.root/'postgres-light.jsonl';connection=None
        try:
            if self.read is None:
                from phase14_pg_stream import ActivityConnection
                from types import SimpleNamespace
                connection=ActivityConnection(self.env)
                proxy=SimpleNamespace(t=self.env.t,sql=connection.sql)
                read=lambda:postgres(proxy)
                (self.env.root/'postgres-light-connection.json').write_text(json.dumps({'pid':connection.pid,'backendStart':connection.birth,'readOnly':True,'closed':False}))
            else:read=self.read
            deadline=time.monotonic()
            with path.open('w',encoding='utf-8') as stream:
                while not self.done.is_set():
                    begin=time.monotonic();row=read()
                    row.update(collectionSeconds=time.monotonic()-begin,startLateSeconds=max(0,begin-deadline))
                    self.samples.append(row);stream.write(json.dumps(row)+'\n');stream.flush()
                    deadline+=self.interval
                    # Do not create catch-up bursts if a read exceeds its period.
                    if deadline<time.monotonic():deadline=time.monotonic()
                    self.done.wait(max(0,deadline-time.monotonic()))
        except Exception as error:self.errors.append(type(error).__name__+': '+str(error))
        finally:
            if connection:
                try:
                    connection.close()
                    (self.env.root/'postgres-light-connection.json').write_text(json.dumps({'pid':connection.pid,'backendStart':connection.birth,'readOnly':True,'closed':True}))
                except Exception as error:self.errors.append('connection cleanup: '+str(error))
    def stop(self):
        self.done.set();self.thread.join(timeout=15)
        if self.thread.is_alive():self.errors.append('light sampler did not stop')
        gaps=[b['time']-a['time'] for a,b in zip(self.samples,self.samples[1:])]
        return {'intervalSeconds':self.interval,'samples':len(self.samples),'errors':self.errors,
                'maxGapSeconds':max(gaps,default=None),'collectionSeconds':sum(x['collectionSeconds'] for x in self.samples),
                'connectionMode':'persistent_read_only' if self.read is None else 'injected_test_reader',
                'scope':'target PostgreSQL client activity only; separate from host and application metrics'}


def scoped_containers(containers,seen_generators):
    services={'backend','postgres','redis','postgres-exporter','redis-exporter','prometheus','noop'}
    seen_generators.update(x['id'] for x in containers if x['service']=='k6' and x['state']=='running')
    current=[x for x in containers if x['service'] in services or x['id'] in seen_generators]
    unexpected=[x['id'] for x in containers if x['state']=='running' and x['service'] not in services|{'k6'}]
    return current,unexpected


class Sampler:
    def __init__(self,env):self.env=env;self.previous_requests=None;self.previous_host=None;self.last_blocking=0;self.seen_generators=set()
    def sample(self):
        env=self.env;now=time.time();start=time.monotonic()
        def docker():
            names=env.command(['docker','ps','-aq','--filter','label=com.docker.compose.project='+env.project]).stdout.decode().split()
            if not names:raise RuntimeError('Phase14 containers missing')
            inspect=json.loads(env.command(['docker','inspect',*names]).stdout)
            stats=env.command(['docker','stats','--no-stream','--format','{{json .}}',*names]).stdout.decode()
            # Select evidence fields explicitly; never serialize container Env.
            safe=[{'id':x['Id'],'name':x['Name'],'service':x['Config']['Labels'].get('com.docker.compose.service'),
                   'state':x['State']['Status'],'healthy':x['State'].get('Health',{}).get('Status','not_applicable'),
                   'restartCount':x['RestartCount'],'oom':x['State']['OOMKilled'],'image':x['Image'],
                   'memoryLimit':x['HostConfig']['Memory'],'nanoCpus':x['HostConfig']['NanoCpus'],'cpuset':x['HostConfig']['CpusetCpus']} for x in inspect]
            return safe,[json.loads(line) for line in stats.splitlines() if line.strip()]
        def redis():return parse_redis_info(env.compose('exec','-T','redis','redis-cli','--raw','INFO','all').stdout.decode())
        def host():
            raw=env.compose('exec','-T','postgres','cat','/proc/stat','/proc/vmstat','/proc/meminfo','/proc/net/dev','/proc/sys/fs/file-nr').stdout.decode()
            parsed={'cpu':None,'swapIn':None,'swapOut':None,'interfaces':{},'fileHandles':None}
            for line in raw.splitlines():
                parts=line.split()
                if not parts:continue
                if parts[0]=='cpu':parsed['cpu']=[int(x) for x in parts[1:]]
                if parts[0]=='pswpin':parsed['swapIn']=int(parts[1])
                if parts[0]=='pswpout':parsed['swapOut']=int(parts[1])
                if parts[0]=='MemTotal:':parsed['memoryTotalBytes']=int(parts[1])*1024
                if parts[0]=='MemAvailable:':parsed['memoryAvailableBytes']=int(parts[1])*1024
                if ':' in line and len(parts)>=16 and not parts[0].startswith('Mem'):
                    interface,values=line.split(':',1);values=values.split()
                    if len(values)==16 and all(v.isdigit() for v in values):parsed['interfaces'][interface.strip()]=[int(v) for v in values]
                if len(parts)==3 and all(v.isdigit() for v in parts):parsed['fileHandles']=[int(v) for v in parts]
            if any(parsed[k] is None for k in ('cpu','swapIn','swapOut','fileHandles')):raise RuntimeError('host sampling incomplete')
            return parsed
        with ThreadPoolExecutor(max_workers=5) as pool:
            a=pool.submit(metrics,env);b=pool.submit(postgres_clock_sample,env);c=pool.submit(docker);d=pool.submit(redis)
            h=pool.submit(host)
            m,raw=a.result();pg=b.result();containers,stats=c.result();rd=d.result();host_data=h.result()
        current,unexpected=scoped_containers(containers,self.seen_generators)
        app={x['name'].lstrip('/'):x for x in containers}
        sut_memory=[];gen_memory=[];gen_cpu=[]
        for item in stats:
            service=app.get(item['Name'],{}).get('service')
            memory=float(item['MemPerc'].rstrip('%'))/100;cpu=float(item['CPUPerc'].rstrip('%'))/100
            if service=='k6':
                cores=app[item['Name']]['nanoCpus']/1e9
                if cores<=0:raise RuntimeError('generator CPU budget missing')
                gen_memory.append(memory);gen_cpu.append(cpu/cores)
            elif service in ('backend','postgres','redis'):sut_memory.append(memory)
        requests=m.get('ticketing_http_requests_total',0)
        sample={'time':now,'collectionSeconds':time.monotonic()-start,'metrics':m,'containers':containers,'dockerStats':stats,
                'correctnessFailure':False,'restarted':any(x['restartCount'] for x in current),
                'oom':any(x['oom'] for x in current),'unhealthy':any(x['healthy']=='unhealthy' for x in current) or any(x['state']!='running' for x in current if x['service'] in ('backend','postgres','redis')),
                'wrongEnvironment':bool(unexpected),'excludedHistoricalContainers':[x['id'] for x in containers if x not in current],'swapping':self.previous_host is not None and (host_data['swapIn']>self.previous_host['swapIn'] or host_data['swapOut']>self.previous_host['swapOut']),
                'swapInDelta':host_data['swapIn']-self.previous_host['swapIn'] if self.previous_host else 0,
                'swapOutDelta':host_data['swapOut']-self.previous_host['swapOut'] if self.previous_host else 0,
                'networkExhausted':False,'fdExhausted':host_data['fileHandles'][0]>=host_data['fileHandles'][2]*.9,
                'generatorMemoryFraction':max(gen_memory,default=0),'generatorCpuFraction':max(gen_cpu,default=0),
                'clockSkewMs':pg['clockSkewMs'],'clockUncertaintyMs':pg['clockUncertaintyMs'],'dropped':0,'memoryFraction':max(sut_memory,default=0),
                'transactionWaiters':m.get('ticketing_db_transaction_acquire_in_flight',0),
                'transactionOldestSeconds':m.get('ticketing_db_transaction_acquire_oldest_seconds',0),
                'httpInflight':m.get('ticketing_http_requests_in_flight',0),
                'redisInflight':m.get('ticketing_redis_operations_in_flight',0),
                'hashQueue':m.get('ticketing_password_hash_queue_depth',0),
                'seatQueue':m.get('ticketing_seat_map_compute_queue_depth',0),
                'completionsSinceLast':requests-(self.previous_requests if self.previous_requests is not None else requests),
                'pgLockWaits':pg['lockWaits'],'pgIdleTransaction':pg['idleTransaction'],'pgIdleAborted':pg['idleAborted'],'pgBlocking':0,
                'hostEvidence':host_data,'physicalNetworkCapacity':'not_available','measurementValid':False}
        if self.previous_host:
            delta=[b-a for a,b in zip(self.previous_host['cpu'],host_data['cpu'])];total=sum(delta)
            sample['cpuStealFraction']=delta[7]/total if total else None
            sample['ioWaitFraction']=delta[4]/total if total else None
            sample['networkExhausted']=any(any(v[i]>self.previous_host['interfaces'].get(k,v)[i] for i in (2,3,10,11)) for k,v in host_data['interfaces'].items())
        self.previous_host=host_data
        # Queue capacities come from the unchanged running backend config.
        from pathlib import Path
        config=json.loads((Path(__file__).resolve().parents[2]/'backend/config/config.phase14.json').read_text(encoding='utf-8'))['custom_config']
        sample['hashQueueFraction']=sample['hashQueue']/config['authentication']['password_hash_queue_capacity']
        sample['seatQueueFraction']=sample['seatQueue']/config['seat_map_compute_queue_capacity']
        if pg['lockWaits'] and now-self.last_blocking>=env.t['generator']['sampleSeconds']:
            sample['blocking']=json.loads(env.sql("SELECT COALESCE(json_agg(row_to_json(x)),'[]') FROM (SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE application_name='ticketing_backend_phase14' AND state='active' AND wait_event_type='Lock') x;"))
            sample['pgBlocking']=len(sample['blocking']);self.last_blocking=now
        self.previous_requests=requests
        return sample,pg,rd,raw
