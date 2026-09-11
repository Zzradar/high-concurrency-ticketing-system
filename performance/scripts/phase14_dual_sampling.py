"""Host /proc observations are collected on the named host, never in PostgreSQL."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOST_PROGRAM = r'''
import pathlib,json,time,os,shutil,hashlib
p=pathlib.Path('/proc');d={'time':time.time(),'cpuCount':os.cpu_count()}
d['identity']=hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest()
d['cpu']=[int(x) for x in (p/'stat').read_text().splitlines()[0].split()[1:9]]
vm=dict(line.split() for line in (p/'vmstat').read_text().splitlines())
d['swapIn']=int(vm['pswpin']);d['swapOut']=int(vm['pswpout'])
mem={line.split(':')[0]:int(line.split()[1])*1024 for line in (p/'meminfo').read_text().splitlines()}
d['memoryTotalBytes']=mem['MemTotal'];d['memoryAvailableBytes']=mem['MemAvailable']
d['fileHandles']=[int(x) for x in (p/'sys/fs/file-nr').read_text().split()]
d['interfaces']={line.split(':')[0].strip():[int(x) for x in line.split(':')[1].split()] for line in (p/'net/dev').read_text().splitlines()[2:]}
disk=shutil.disk_usage('/srv/phase14/repo');d['diskFreeBytes']=disk.free;d['diskTotalBytes']=disk.total
v=os.statvfs('/srv/phase14/repo');d['inodesFree']=v.f_favail;d['inodesTotal']=v.f_files
d['diskstats']=(p/'diskstats').read_text().splitlines()
print(json.dumps(d))
'''


def host_sample(executor, previous=None):
    start=time.monotonic()
    x=json.loads(executor.run(['python3','-c',HOST_PROGRAM],timeout=15).stdout)
    x['collectionSeconds']=time.monotonic()-start
    return host_delta(x,previous)


def host_delta(x,previous=None):
    x['memoryFraction']=1-x['memoryAvailableBytes']/x['memoryTotalBytes']
    for key in ('swapIn','swapOut'): x[key+'Delta']=x[key]-previous[key] if previous else 0
    x['cpuFraction']=0; x['networkErrors']=False
    if previous:
        delta=[a-b for a,b in zip(x['cpu'],previous['cpu'])];total=sum(delta)
        x['cpuFraction']=(total-delta[3]-delta[4])/total if total>0 else 0
        x['ioWaitFraction']=delta[4]/total if total>0 else 0
        x['cpuStealFraction']=delta[7]/total if total>0 else 0
        x['networkErrors']=any(any(v[i]>previous['interfaces'].get(k,v)[i] for i in (2,3,10,11)) for k,v in x['interfaces'].items())
        seconds=x['time']-previous['time']
        x['networkBytesPerSecond']={k:{'receive':max(0,v[0]-previous['interfaces'].get(k,v)[0])/seconds,
                                     'transmit':max(0,v[8]-previous['interfaces'].get(k,v)[8])/seconds} for k,v in x['interfaces'].items()}
    return x


def safe_containers(items):
    return [{'id':x['Id'],'name':x['Name'].lstrip('/'),'service':x['Config']['Labels']['com.docker.compose.service'],
             'runId':x['Config']['Labels'].get('ticketing.phase14.run'),'state':x['State']['Status'],
             'healthy':x['State'].get('Health',{}).get('Status','not_applicable'),'oom':x['State']['OOMKilled'],
             'restartCount':x['RestartCount'],'image':x['Image'],'nanoCpus':x['HostConfig']['NanoCpus'],
             'memoryLimit':x['HostConfig']['Memory']} for x in items]


def probe_host(role,project,detailed):
    """One on-host process per sample amortizes SSH setup across all observations."""
    import subprocess,re
    from phase14_topology import verify_container,SUT_SERVICES,LOAD_SERVICES
    if role not in ('sut','load') or not re.fullmatch(r'phase14-[a-z0-9-]+-'+role,project):raise ValueError('invalid probe role')
    prefix=['sudo','-n'] if role=='load' else []
    def docker(*args):return subprocess.check_output([*prefix,'docker',*args],timeout=15)
    begin=time.monotonic()
    ids=docker('ps','-aq','--filter','label=com.docker.compose.project='+project).decode().split()
    items=json.loads(docker('inspect',*ids)) if ids else []
    for item in items:verify_container(item,project,SUT_SERVICES if role=='sut' else LOAD_SERVICES)
    active=[x['Id'] for x in items if x['State']['Running']]
    stats=[];cpu={}
    if detailed:
        for item in items:
            if item['Id'] not in active:continue
            # Engine's one-shot API avoids Docker CLI's two-cycle stats wait.
            # Only an existing local Unix socket is used; no daemon port is opened.
            url='http://localhost/v1.52/containers/'+item['Id']+'/stats?stream=false&one-shot=true'
            value=json.loads(subprocess.check_output([*prefix,'curl','--fail','--silent','--show-error','--max-time','5',
                              '--unix-socket','/var/run/docker.sock',url],timeout=8))
            memory=value['memory_stats'];usage=memory['usage']-memory.get('stats',{}).get('inactive_file',0)
            cs=value['cpu_stats'];c={'total':cs['cpu_usage']['total_usage'],'system':cs.get('system_cpu_usage',0),'cores':cs['online_cpus']}
            cpu[item['Id']]=c
            stats.append({'Name':item['Name'].lstrip('/'),'Id':item['Id'],'MemPerc':str(100*usage/memory['limit'])+'%',
                          'CPUPerc':'0%','read':value['read'],'cpuCounters':c,'memoryStats':memory,'networkStats':value.get('networks',{})})
    namespace={}
    exec(HOST_PROGRAM.replace('print(json.dumps(d))',''),namespace)
    host=namespace['d'];host['collectionSeconds']=time.monotonic()-begin;host['containerCpu']=cpu
    return {'host':host,'containers':safe_containers(items),'stats':stats}


def role_sample(env,role,previous,detailed):
    project=env.project if role=='sut' else env.load_project
    args=['python3','/srv/phase14/repo/performance/scripts/phase14_dual_sampling.py','--probe',role,project]
    if detailed:args.append('--detailed')
    payload=json.loads(getattr(env,role).run(args,timeout=30).stdout)
    for row in payload['stats']:
        old=(previous or {}).get('containerCpu',{}).get(row['Id']);current=row['cpuCounters']
        if old:
            elapsed=current['system']-old['system'];used=current['total']-old['total']
            if elapsed<=0 or used<0:raise RuntimeError('container CPU counters invalid')
            row['CPUPerc']=str(100*used/elapsed*current['cores'])+'%'
    return host_delta(payload['host'],previous),payload['containers'],payload['stats']


def containers(env, role, detailed=True):
    items=env.inspect_role(role)
    safe=[{'id':x['Id'],'name':x['Name'].lstrip('/'),'service':x['Config']['Labels']['com.docker.compose.service'],
           'runId':x['Config']['Labels'].get('ticketing.phase14.run'),'state':x['State']['Status'],
           'healthy':x['State'].get('Health',{}).get('Status','not_applicable'),'oom':x['State']['OOMKilled'],
           'restartCount':x['RestartCount'],'image':x['Image'],'nanoCpus':x['HostConfig']['NanoCpus'],
           'memoryLimit':x['HostConfig']['Memory']} for x in items]
    active=[x['id'] for x in safe if x['state']=='running']
    raw=env.docker(role,'stats','--no-stream','--format','{{json .}}',*active).stdout.decode() if active and detailed else ''
    return safe,[json.loads(line) for line in raw.splitlines() if line.strip()]


class DualSampler:
    def __init__(self, env, *, load_only=False, detailed=True):
        self.env=env;self.load_only=load_only;self.previous={};self.previous_requests=None;self.detailed=detailed

    def sample(self):
        from phase14_sampling import metrics, postgres_clock_sample
        from performance_evidence import parse_redis_info
        env=self.env;start=time.monotonic();now=time.time()
        roles=['load'] if self.load_only else ['sut','load']
        hosts={};rows={};stats={}
        with ThreadPoolExecutor(max_workers=7) as pool:
            h={r:pool.submit(role_sample,env,r,self.previous.get(r),self.detailed) for r in roles}
            if not self.load_only:
                a=pool.submit(metrics,env);p=pool.submit(postgres_clock_sample,env)
                d=pool.submit(env.compose,'exec','-T','redis','redis-cli','--raw','INFO','all')
            for r in roles: hosts[r],rows[r],stats[r]=h[r].result()
            if not self.load_only: m,raw=a.result();pg=p.result();rd=parse_redis_info(d.result().stdout.decode())
            else:m,raw,pg,rd={},'',{},{}
        self.previous=hosts
        load=[x for x in rows['load'] if x['service']=='noop' or x['runId']==env.root.name]
        sut=rows.get('sut',[]);current=sut+load
        mem=[];gen_mem=[];gen_cpu=[]
        for role in roles:
            by_name={x['name']:x for x in rows[role]}
            for row in stats[role]:
                item=by_name[row['Name']];memory=float(row['MemPerc'].rstrip('%'))/100
                if role=='load' and item in load:
                    gen_mem.append(memory);cores=item['nanoCpus']/1e9
                    if cores<=0: raise RuntimeError('generator CPU limit missing')
                    gen_cpu.append(float(row['CPUPerc'].rstrip('%'))/100/cores)
                elif role=='sut' and item['service'] in ('backend','postgres','redis'):mem.append(memory)
        requests=m.get('ticketing_http_requests_total',0);h=hosts['load']
        config=json.loads((Path(__file__).resolve().parents[2]/'backend/config/config.phase14.json').read_text())['custom_config']
        x={'time':now,'collectionSeconds':time.monotonic()-start,'sutHost':hosts.get('sut'),'sutContainers':sut,
           'loadHost':h,'loadGenerators':load,'sutDockerStats':stats.get('sut',[]),'loadDockerStats':stats['load'],
           'metrics':m,'measurementValid':True,'correctnessFailure':False,
           'restarted':any(v['restartCount'] for v in current),'oom':any(v['oom'] for v in current),
           'unhealthy':any(v['healthy']=='unhealthy' for v in current) or any(v['state']!='running' for v in sut),
           'wrongEnvironment':False,'swapping':any(v['swapInDelta'] or v['swapOutDelta'] for v in hosts.values()),
           'swapInDelta':sum(v['swapInDelta'] for v in hosts.values()),'swapOutDelta':sum(v['swapOutDelta'] for v in hosts.values()),
           'networkExhausted':any(v['networkErrors'] for v in hosts.values()),
           'fdExhausted':any(v['fileHandles'][0]>=v['fileHandles'][2]*.9 for v in hosts.values()),
           'generatorMemoryFraction':max([h['memoryFraction'],*gen_mem]),'generatorCpuFraction':max([h['cpuFraction'],*gen_cpu]),
           'memoryFraction':max([hosts.get('sut',{}).get('memoryFraction',0),*mem]),
           'clockSkewMs':pg.get('clockSkewMs',0),'clockUncertaintyMs':pg.get('clockUncertaintyMs',0),'dropped':0,
           'transactionWaiters':m.get('ticketing_db_transaction_acquire_in_flight',0),
           'transactionOldestSeconds':m.get('ticketing_db_transaction_acquire_oldest_seconds',0),
           'httpInflight':m.get('ticketing_http_requests_in_flight',0),'redisInflight':m.get('ticketing_redis_operations_in_flight',0),
           'hashQueue':m.get('ticketing_password_hash_queue_depth',0),'seatQueue':m.get('ticketing_seat_map_compute_queue_depth',0),
           'completionsSinceLast':requests-(self.previous_requests if self.previous_requests is not None else requests),
           'pgLockWaits':pg.get('lockWaits',0),'pgIdleTransaction':pg.get('idleTransaction',0),'pgIdleAborted':pg.get('idleAborted',0),'pgBlocking':0}
        x['hashQueueFraction']=x['hashQueue']/config['authentication']['password_hash_queue_capacity']
        x['seatQueueFraction']=x['seatQueue']/config['seat_map_compute_queue_capacity']
        if x['pgLockWaits']:
            x['blocking']=json.loads(env.sql("SELECT COALESCE(json_agg(row_to_json(x)),'[]') FROM (SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE application_name='ticketing_backend_phase14' AND state='active' AND wait_event_type='Lock') x;"))
            x['pgBlocking']=len(x['blocking'])
        self.previous_requests=requests
        return x,pg,rd,raw


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--probe',choices=['sut','load'],required=True)
    parser.add_argument('project');parser.add_argument('--detailed',action='store_true');args=parser.parse_args()
    print(json.dumps(probe_host(args.probe,args.project,args.detailed)))
