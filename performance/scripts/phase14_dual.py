"""Dual-host Environment. Coordinator and every input live on Load."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import subprocess
import time

from run_phase14 import Environment, ROOT, COMPOSE, GENERATED, guard_model, write
from phase14_topology import (WORKDIR, SUT_SERVICES, LOAD_SERVICES, LoadExecutor,
                              SutExecutor, digest, verify_container)
from phase14_evidence import sha256


class DualEnvironment(Environment):
    dual = True

    def __init__(self, t, root, topology):
        if str(ROOT) != WORKDIR:
            raise ValueError('dual coordinator must run in Load repository')
        super().__init__(t, root, project=topology.values['sutProject'])
        self.topology = topology
        self.load_project = topology.values['loadProject']
        self.base = topology.values['sutBaseUrl']
        self.data = GENERATED/('dual-'+t['mode']+'-v'+str(t['version']))
        self.env['PHASE14_DATA_ROOT'] = str(self.data)
        self.env['PHASE14_BIND_ADDRESS'] = topology.values['sutBindAddress']
        # Ownership is validated explicitly; retained old shards are evidence.
        self.env['COMPOSE_IGNORE_ORPHANS'] = 'true'
        self.sut = SutExecutor(topology, self.root/'commands.jsonl')
        self.load = LoadExecutor(topology, self.root/'commands.jsonl')
        self.runtime = Path('/srv/phase14/runtime')
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        self.models = {}
        self.created = time.time()
        self.generators = {}

    def command(self, args, **kwargs):
        # Legacy observational Docker calls refer to the SUT, never Load.
        executor = self.sut if args[0] == 'docker' else self.load
        return executor.run(args, **kwargs)

    def docker(self, role, *args, **kwargs):
        prefix = self.topology.values['loadDockerPrefix'] if role == 'load' else []
        return getattr(self, role).run([*prefix, 'docker', *args], **kwargs)

    def role_file(self, role):
        project = self.load_project if role == 'load' else self.project
        return str(self.runtime/(project+'-'+self.t['mode']+'.json'))

    def resolve(self, role):
        project = self.load_project if role == 'load' else self.project
        variables = {k:v for k,v in self.env.items() if k.startswith('PHASE14_')}
        variables['PHASE14_PROJECT'] = project
        executor = getattr(self, role)
        prefix = self.topology.values['loadDockerPrefix'] if role == 'load' else []
        raw = executor.run([*prefix,'docker','compose','--profile','load','-p',project,'-f',str(COMPOSE),
                            'config','--format','json'], env=variables)
        model = json.loads(raw.stdout)
        guard_model(model, project, self.data, self.t)
        allowed = LOAD_SERVICES if role == 'load' else SUT_SERVICES
        model['services'] = {k:v for k,v in model['services'].items() if k in allowed}
        if set(model['services']) != allowed: raise ValueError('missing role service')
        for service in model['services'].values(): service.pop('profiles', None)
        if role == 'load':
            model['volumes'] = {}
        else:
            for service, address, port in [('backend',self.topology.values['sutBindAddress'],self.t['environment']['localPort']),
                                            ('prometheus','127.0.0.1',self.t['environment']['prometheusPort'])]:
                ports = model['services'][service].get('ports', [])
                if len(ports)!=1 or ports[0].get('host_ip')!=address or int(ports[0]['published'])!=port:
                    raise ValueError('unsafe service binding')
        payload = json.dumps(model).encode()
        program = "import os,pathlib,sys;os.umask(0o077);p=pathlib.Path(sys.argv[1]);p.parent.mkdir(mode=0o700,exist_ok=True);p.write_bytes(sys.stdin.buffer.read());p.chmod(0o600)"
        executor.run(['python3','-c',program,self.role_file(role)], input=payload)
        self.models[role] = model
        return model

    def compose_role(self, role, *args, **kwargs):
        allowed = LOAD_SERVICES if role=='load' else SUT_SERVICES
        if args[0] in ('down','rm','kill','prune'): raise ValueError('destructive Compose action forbidden')
        if args[0] in ('up','stop','start','restart'):
            selected = [x for x in args[1:] if not x.startswith('-')]
            if not selected or not set(selected)<=allowed: raise ValueError('role service whitelist violation')
        if role not in self.models: self.resolve(role)
        project = self.load_project if role=='load' else self.project
        return self.docker(role, 'compose','-p',project,'-f',self.role_file(role), *args, **kwargs)

    def compose(self, *args, **kwargs): return self.compose_role('sut', *args, **kwargs)

    def inspect_role(self, role):
        project = self.load_project if role=='load' else self.project
        ids = self.docker(role,'ps','-aq','--filter','label=com.docker.compose.project='+project).stdout.decode().split()
        if not ids: return []
        items = json.loads(self.docker(role,'inspect',*ids).stdout)
        for item in items:
            verify_container(item,project,LOAD_SERVICES if role=='load' else SUT_SERVICES)
            service=item['Config']['Labels']['com.docker.compose.service']
            bindings=item.get('HostConfig',{}).get('PortBindings') or {}
            if service in ('backend','prometheus'):
                target='8080/tcp' if service=='backend' else '9090/tcp'
                address=self.topology.values['sutBindAddress'] if service=='backend' else '127.0.0.1'
                port=self.t['environment']['localPort' if service=='backend' else 'prometheusPort']
                if bindings!={target:[{'HostIp':address,'HostPort':str(port)}]}:raise ValueError('running service binding mismatch')
            elif bindings:raise ValueError('unexpected published port')
            for mount in item.get('Mounts',[]):
                if mount['Type']=='volume' and (role=='load' or mount.get('Name') not in {self.project+'_postgres',self.project+'_prometheus'}):
                    raise ValueError('unexpected mounted volume')
        return items

    def validate(self):
        addresses = json.loads(self.sut.run(['ip','-j','-4','addr','show']).stdout)
        if not any(a.get('local')==self.topology.values['sutBindAddress'] and a.get('scope')=='global'
                   for row in addresses for a in row.get('addr_info',[])):
            raise ValueError('SUT private address does not match interface')
        for role in ('sut','load'):
            self.resolve(role)
            self.inspect_role(role)
            project = self.load_project if role=='load' else self.project
            names = self.docker(role,'volume','ls','-q','--filter','label=com.docker.compose.project='+project).stdout.decode().split()
            allowed = set() if role=='load' else {self.project+'_postgres',self.project+'_prometheus'}
            if not set(names)<=allowed: raise ValueError('unknown role volume')
            for name in allowed:
                result = self.docker(role,'volume','inspect',name,check=False)
                if result.returncode==0:
                    labels = json.loads(result.stdout)[0].get('Labels') or {}
                    if labels.get('ticketing.phase14')!='capacity' or labels.get('com.docker.compose.project')!=project:
                        raise ValueError('volume ownership mismatch')
        write(self.root/'topology.json',self.topology.public())
        write(self.root/'role-compose.json',{'sut':{'project':self.project,'services':sorted(SUT_SERVICES),
              'volumes':[self.project+'_postgres',self.project+'_prometheus'],'backendBinding':'SUT-private','prometheusBinding':'SUT-loopback'},
              'load':{'project':self.load_project,'services':sorted(LOAD_SERVICES),'volumes':[]}})
        return self.models['sut']

    def sql(self, query):
        return self.compose('exec','-T','-e','PGAPPNAME=phase14_sampler','postgres','psql','-U','ticketing','-d','ticketing',
                            '--set=ON_ERROR_STOP=1','-At','-F','\t',input=query.encode(),timeout=30).stdout.decode().strip()

    def psql_popen(self):
        if 'sut' not in self.models: self.resolve('sut')
        return self.sut.popen(['docker','compose','-p',self.project,'-f',self.role_file('sut'),
                'exec','-T','-e','PGAPPNAME=phase14_sampler','postgres','psql','-U','ticketing','-d','ticketing',
                '-qAt','--set=ON_ERROR_STOP=1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,encoding='utf-8')

    def fingerprint(self):
        # Hash every row in deterministic table order; do not export session secrets.
        tables = json.loads(self.sql("SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public';"))
        hashes = {}
        for name in tables:
            if not name.replace('_','').isalnum(): raise ValueError('unsafe table identifier')
            hashes[name] = self.sql('SELECT md5(COALESCE(string_agg(h,\'\' ORDER BY h),\'\')) FROM (SELECT md5(row_to_json(t)::text) h FROM "'+name+'" t) s;')
        return {'tables':hashes,'sha256':digest(hashes)}

    def reset(self, *, yes=False, snapshot=None):
        self.validate()
        if not yes: return
        manifest = json.loads((self.data/'dataset-manifest.json').read_text())
        if manifest['targetsSha256']!=self.t['sourceSha256']: raise ValueError('dataset targets mismatch')
        for name, item in manifest['files'].items():
            if Path(name).name!=name or sha256(self.data/name)!=item['sha256']: raise ValueError('dataset hash mismatch')
        if snapshot and (snapshot.resolve()!=(self.data/'base.dump').resolve() or sha256(snapshot)!=snapshot.with_suffix('.sha256').read_text().strip()):
            raise ValueError('snapshot identity mismatch')
        self.compose('stop','backend','postgres-exporter','redis-exporter','prometheus')
        self.compose('up','-d','--wait','postgres','redis')
        before = self.fingerprint()
        if snapshot:
            self.compose('exec','-T','postgres','pg_restore','-U','ticketing','-d','ticketing','--clean','--if-exists','--exit-on-error',input_file=snapshot,timeout=900)
        else:
            self.compose('exec','-T','postgres','psql','-U','ticketing','-d','ticketing','--set=ON_ERROR_STOP=1',input_file=self.data/'dataset.sql',timeout=900)
        after = self.fingerprint()
        baseline = self.data/'database-fingerprint.json'
        if snapshot:
            if after != json.loads(baseline.read_text()): raise RuntimeError('restored database fingerprint mismatch')
        else:
            if baseline.exists() and json.loads(baseline.read_text())!=after: raise ValueError('existing baseline differs')
            write(baseline,after)
        self.inspect_role('sut')
        self.compose('exec','-T','redis','redis-cli','FLUSHALL','SYNC')
        if self.compose('exec','-T','redis','redis-cli','DBSIZE').stdout.strip()!=b'0': raise RuntimeError('Redis reset failed')
        write(self.root/'reset.json',{'snapshotSha256':sha256(snapshot) if snapshot else None,'before':before,'after':after,'baseline':json.loads(baseline.read_text()),'redisDbsize':0,'passed':True})
        self.reset_statement_statistics()
        self.compose('up','-d','--wait','backend','postgres-exporter','redis-exporter','prometheus')
        self.http('/health')

    def reset_statement_statistics(self):
        # Restore creates new relation OIDs. Preserve old counters before clearing
        # this dedicated database's entries, while application clients are stopped.
        from phase14_sampling import pg_snapshot
        self.inspect_role('sut')
        write(self.root/'postgres-statements-before-reset.json',pg_snapshot(self))
        self.sql("SELECT pg_stat_statements_reset(0,(SELECT oid FROM pg_database WHERE datname=current_database()),0);")
        write(self.root/'postgres-statements-after-reset.json',pg_snapshot(self))

    def prometheus(self, path):
        url='http://127.0.0.1:'+str(self.t['environment']['prometheusPort'])+path
        return json.loads(self.sut.run(['curl','--fail','--silent','--show-error','--max-time','20',url]).stdout)

    def child(self, root):
        child=DualEnvironment(self.t,root,self.topology)
        child.deadline_at=getattr(self,'deadline_at',None)
        return child

    def start_generator(self, argv, log):
        if getattr(self,'deadline_at',None) and time.time()>=self.deadline_at:
            raise RuntimeError('core wall-clock deadline; generator launch forbidden')
        # Adapt the existing frozen workload invocation, not its business input.
        argv=list(argv);argv[argv.index('-p')+1]=self.load_project
        first=argv.index('-f');argv[first+1]=self.role_file('load')
        if 'load' not in self.models: self.resolve('load')
        for i,arg in enumerate(argv):
            if arg.startswith('BASE_URL=') and arg!='BASE_URL=http://noop:8080':argv[i]='BASE_URL='+self.base
            if arg=='LOGIN_PASSWORD':argv[i]='LOGIN_PASSWORD='+self.env['LOGIN_PASSWORD']
        if not any(x.startswith('BASE_URL=') for x in argv):
            argv[argv.index('k6') : argv.index('k6')] = ['-e','BASE_URL='+self.base]
        name=argv[argv.index('--name')+1]
        # Keep the externally expected name, but labels and project identify Load.
        argv[argv.index('run')+1:argv.index('run')+1]=['--user',str(os.getuid())+':'+str(os.getgid()),'--label','ticketing.phase14.run='+self.root.name]
        image=json.loads(self.docker('load','image','inspect','grafana/k6:2.2.0').stdout)[0]['Id']
        self.generators[name]={'image':image,'createdAfter':time.time()-1}
        prefix=self.topology.values['loadDockerPrefix']
        return self.load.popen([*prefix,*argv],stdout=log,stderr=subprocess.STDOUT,env=self.env)

    def stop_generators(self, names=None):
        stopped=[];running=[]
        for name in names or self.generators:
            if name not in self.generators: raise ValueError('not a registered run shard')
            expected=self.generators[name]
            result=self.docker('load','inspect',name,check=False)
            if result.returncode: continue
            item=json.loads(result.stdout)[0]
            identity=verify_container(item,self.load_project,{'k6'},run_id=self.root.name,name=name,
                                      image=expected['image'],created_after=expected['createdAfter'])
            if item['State']['Running']:running.append(identity)
            stopped.append(identity)
        # Docker stops this verified set concurrently, within the abort guard.
        if running:self.docker('load','stop','--time','2',*running)
        with (self.root/'stop-evidence.jsonl').open('a') as out:
            out.write(json.dumps({'runId':self.root.name,'project':self.load_project,'verifiedIds':stopped,'at':time.time()})+'\n')
        return stopped
