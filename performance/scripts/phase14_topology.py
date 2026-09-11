"""Strict dual-host configuration and role-bound, redacted subprocess transport."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import queue
import threading
import time
from urllib.parse import urlsplit

WORKDIR = '/srv/phase14/repo'
FIELDS = {'mode', 'sutSshAlias', 'sutWorkdir', 'sutBaseUrl', 'sutBindAddress',
          'sutProject', 'loadProject', 'loadDockerPrefix', 'resultRoot'}
SUT_SERVICES = {'postgres', 'redis', 'backend', 'postgres-exporter', 'redis-exporter', 'prometheus'}
LOAD_SERVICES = {'noop', 'k6'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def redact(value):
    text = str(value)
    text = re.sub(r'https?://[^\s\"\']+', '<redacted-url>', text)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '<address>', text)
    text = re.sub(r'(?i)(password|passwd|token|secret|cookie|csrf)([^\s]*[=:])[^\s]+', r'\1\2<redacted>', text)
    return text


@dataclass(frozen=True)
class Topology:
    values: dict

    @classmethod
    def parse(cls, values, targets, *, root=WORKDIR):
        if not isinstance(values, dict) or set(values) != FIELDS:
            raise ValueError('topology fields missing or unknown')
        v = dict(values)
        if v['mode'] != 'dual' or v['sutSshAlias'] != 'phase14-sut' or v['sutWorkdir'] != WORKDIR:
            raise ValueError('invalid fixed topology identity')
        if v['loadDockerPrefix'] not in ([], ['sudo']):
            raise ValueError('unsafe Docker prefix')
        for role in ('sut', 'load'):
            name = v[role+'Project']
            if not isinstance(name, str) or not re.fullmatch(r'phase14-[a-z0-9]+(?:-[a-z0-9]+)*-'+role, name):
                raise ValueError('invalid role project')
        if v['sutProject'] == v['loadProject']:
            raise ValueError('role projects overlap')
        try:
            address = ipaddress.IPv4Address(v['sutBindAddress'])
            url = urlsplit(v['sutBaseUrl'])
            private = any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
            if not private or url.scheme != 'http' or url.hostname != str(address) or url.port != targets['environment']['localPort']:
                raise ValueError('invalid private target or port')
            if url.username or url.password or url.path or url.query or url.fragment or '?' in v['sutBaseUrl'] or '#' in v['sutBaseUrl']:
                raise ValueError('URL must contain only private host and frozen port')
        except (TypeError, AttributeError):
            raise ValueError('invalid target type') from None
        result = PurePosixPath(v['resultRoot'])
        allowed = PurePosixPath(root)/'performance/results'
        if not result.is_absolute() or '..' in result.parts or not result.is_relative_to(allowed):
            raise ValueError('results escape repository')
        return cls(v)

    @classmethod
    def read(cls, path, targets):
        path = Path(path)
        if path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
            raise ValueError('topology must be a regular 0600 runtime file')
        return cls.parse(json.loads(path.read_text()), targets)

    def public(self):
        v = self.values
        return {'mode': 'dual', 'sutRole': v['sutSshAlias'], 'loadRole': 'phase14-load',
                'sutProject': v['sutProject'], 'loadProject': v['loadProject'],
                'portSource': 'targets.environment.localPort', 'privateAddressValidated': True,
                'addressSha256': digest(v['sutBindAddress']), 'fingerprint': digest(v)}


class Executor:
    def __init__(self, role, topology, log):
        self.role, self.topology, self.log = role, topology, Path(log)

    def argv(self, args, env=None):
        if not isinstance(args, (list, tuple)) or not args or not all(isinstance(x, str) and '\0' not in x for x in args):
            raise ValueError('command requires string argument array')
        if self.role == 'sut':
            command = ['env', *[k+'='+v for k,v in (env or {}).items()], *args]
            return ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                    '-o', 'ConnectTimeout=10', 'phase14-sut',
                    'cd '+shlex.quote(WORKDIR)+' && exec '+shlex.join(command)]
        if args[0]=='sudo':
            variables=[k+'='+v for k,v in (env or {}).items() if k.startswith('PHASE14_')]
            return ['sudo','-n',*(['env',*variables] if variables else []),*args[1:]]
        return list(args)

    def record(self, args, began, code, elapsed, **extra):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        # stdin and environment are deliberately absent, even on failure.
        safe = [redact(x) for x in args]
        if any(x in ('psql', 'pg_restore', 'python3') for x in args):
            safe = [x for x in safe[:5]] + ['<stdin-or-program-omitted>']
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'role': self.role, 'argv': safe, 'startedAt': began,
                                     'exitCode': code, 'seconds': elapsed, **extra})+'\n')

    def run(self, args, *, input=None, input_file=None, output_file=None, check=True, timeout=120, env=None):
        began = datetime.now(timezone.utc).isoformat(); start = time.monotonic()
        source = open(input_file, 'rb') if input_file else None
        destination = open(output_file, 'wb') if output_file else None
        try:
            kwargs = {'stdin': source} if source else {'input': input}
            result = subprocess.run(self.argv(args, env), stdout=destination or subprocess.PIPE,
                                    stderr=subprocess.PIPE, cwd=WORKDIR, timeout=timeout,
                                    env={**os.environ, **(env or {})} if self.role=='load' else None, **kwargs)
            self.record(args, began, result.returncode, time.monotonic()-start,
                        errorType='command_failed' if result.returncode else None)
            if check and result.returncode:
                raise RuntimeError(self.role+' command failed (exit '+str(result.returncode)+'); sensitive stderr withheld')
            return result
        except subprocess.TimeoutExpired:
            self.record(args, began, 124, time.monotonic()-start, errorType='timeout')
            raise RuntimeError(self.role+' command timed out') from None
        finally:
            if source: source.close()
            if destination: destination.close()

    def popen(self, args, *, env=None, **kwargs):
        self.record(args, datetime.now(timezone.utc).isoformat(), None, 0, event='spawn')
        return subprocess.Popen(self.argv(args, env), cwd=WORKDIR,
                                env={**os.environ, **(env or {})} if self.role=='load' else None, **kwargs)


class LoadExecutor(Executor):
    def __init__(self, topology, log): super().__init__('load', topology, log)


class SutExecutor(Executor):
    def __init__(self, topology, log): super().__init__('sut', topology, log)


class HostClock:
    """Establish SSH before timing midpoint samples; terminate only this pipe."""
    def __init__(self, executor):
        program="import sys,time;print('ready',flush=True)\nfor line in sys.stdin:\n if line.strip()=='quit':break\n print(time.time(),flush=True)"
        self.process=executor.popen(['python3','-u','-c',program],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.lines=queue.Queue()
        def read():
            for line in self.process.stdout:self.lines.put(line.strip())
            self.lines.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        if self.lines.get(timeout=10)!='ready':self.close();raise RuntimeError('host clock handshake failed')

    def sample(self):
        start=time.time();self.process.stdin.write('time\n');self.process.stdin.flush()
        raw=self.lines.get(timeout=10);end=time.time()
        if raw is None:raise RuntimeError('host clock stream ended')
        value=float(raw)
        return {'remoteUtcSeconds':value,'loadStartUtcSeconds':start,'loadEndUtcSeconds':end,
                'offsetMs':(value-(start+end)/2)*1000,'uncertaintyMs':(end-start)*500,
                'transport':'established_ssh_pipe'}

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.write('quit\n');self.process.stdin.flush();self.process.wait(timeout=5)
        except (OSError,subprocess.TimeoutExpired):
            self.process.terminate();self.process.wait(timeout=5)
        finally:
            self.reader.join(timeout=2)
            for stream in (self.process.stdin,self.process.stdout,self.process.stderr):stream.close()


def verify_container(item, project, services, *, run_id=None, name=None, image=None, created_after=None):
    labels = item.get('Config', {}).get('Labels') or {}
    if labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.service') not in services:
        raise ValueError('container role ownership mismatch')
    if run_id is not None and labels.get('ticketing.phase14.run') != run_id:
        raise ValueError('generator run mismatch')
    if name is not None and item['Name'].lstrip('/') != name:
        raise ValueError('generator name mismatch')
    if image is not None and item['Image'] != image:
        raise ValueError('generator image mismatch')
    if created_after is not None:
        created = datetime.fromisoformat(item['Created'].replace('Z', '+00:00')).timestamp()
        if created < created_after:
            raise ValueError('generator creation precedes run')
    return item['Id']
