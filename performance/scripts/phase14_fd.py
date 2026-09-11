"""Bounded Phase14 FD deployment and explicit reuse of qualified evidence."""
import json
import re
from pathlib import Path

LIMIT = 65535
OVERRIDE = {'services': {'backend': {'ulimits': {'nofile': {'soft': LIMIT, 'hard': LIMIT}}}}}


def parse_limits(text):
    match = re.search(r'^Max open files\s+(\d+)\s+(\d+)\s+files\s*$', text, re.M)
    if not match:
        raise ValueError('backend process nofile unavailable')
    return {'soft': int(match[1]), 'hard': int(match[2])}


def validate_limits(record):
    expected = {'soft': LIMIT, 'hard': LIMIT}
    if {k: record[k] for k in expected} != expected:
        raise ValueError('backend process nofile must be 65535/65535')
    if record['dockerUlimits'] != [{'Name': 'nofile', 'Soft': LIMIT, 'Hard': LIMIT}]:
        raise ValueError('Docker nofile differs from process contract')


def process_sample(item, docker):
    """Read the verified container main PID on SUT, without a docker exec FD."""
    pid = item['State']['Pid']
    if not item['State']['Running'] or pid <= 0:
        raise ValueError('backend process stopped')
    proc = Path('/proc') / str(pid)
    limits = parse_limits((proc / 'limits').read_text())
    count = len(list((proc / 'fd').iterdir()))
    # Docker timestamps let reports deduplicate overlapping five-second windows.
    logs = docker('logs', '--timestamps', '--since', '5s', item['Id']).decode(errors='replace')
    events = [line.split(' ', 1)[0] for line in logs.splitlines()
              if re.search(r'Too many open files|EMFILE|Acceptor.*(?:fail|errno)|(?:FATAL|ERROR).*Acceptor', line, re.I)]
    return {**limits, 'open': count, 'fraction': count / limits['soft'],
            'containerId': item['Id'], 'startedAt': item['State']['StartedAt'],
            'dockerUlimits': item['HostConfig'].get('Ulimits'),
            'errorTimestamps': events, 'logWindowSeconds': 5}


class FdGuard:
    def __init__(self):
        self.high = 0

    def sample(self, record):
        validate_limits(record)
        self.high = self.high + 1 if record['fraction'] >= .85 else 0
        return bool(record['errorTimestamps'] or self.high >= 3)


def apply_override(env, model):
    from copy import deepcopy
    from phase14_campaign import write
    from phase14_evidence import sha256
    model = deepcopy(model)
    original = deepcopy(model)
    model['services']['backend']['ulimits'] = OVERRIDE['services']['backend']['ulimits']
    write(env.root / 'fd-original-role-compose.json', original)
    write(env.root / 'fd-override.json', OVERRIDE)
    write(env.root / 'fd-rendered-role-compose.json', model)
    write(env.root / 'fd-compose-hashes.json', {name: sha256(env.root / name) for name in
          ('fd-original-role-compose.json', 'fd-override.json', 'fd-rendered-role-compose.json')})
    return model


def equivalent_fingerprint(old, new):
    """Only explicitly attested source commits may differ; every input stays bound."""
    source = {'git', 'controlHead', 'controlTree', 'officialOriginHead'}
    if {k: v for k, v in old.items() if k not in source} != {k: v for k, v in new.items() if k not in source}:
        raise ValueError('reused qualification input/image/topology changed')


def delta_guard(args, env, *, immediate=True):
    import time
    from phase14_campaign import current_fingerprint, verify_hashes, verify_referenced_runs, preflight
    from phase14_evidence import sha256
    if not (env.dual and env.fd_resume and args.yes and args.formal_approved and args.core):
        raise ValueError('FD resume requires explicit dual formal authorization')
    d = json.loads(args.delta_qualification.read_text())
    if d.get('kind') != 'phase14-fd-delta' or d.get('status') != 'pass' or d['shards'] != args.shards:
        raise ValueError('FD delta qualification invalid')
    if time.time() >= d['hardDeadlineAt']:
        raise ValueError('FD resume window expired')
    oldpath = Path(d['originalQualification']['path'])
    if sha256(oldpath) != d['originalQualification']['sha256']:
        raise ValueError('original qualification hash changed')
    q = json.loads(oldpath.read_text())
    if q['status'] != 'pass' or q['topologyMode'] != 'dual' or q['shards'] != args.shards:
        raise ValueError('original qualification failed')
    if time.time() - q['createdAt'] > env.t['environment']['retentionDays'] * 86400:
        raise ValueError('original qualification expired')
    current = current_fingerprint(env)
    if current != d['fingerprint']:
        raise ValueError('delta source or inputs changed')
    equivalent_fingerprint(q['fingerprint'], current)
    allowed = {'performance/scripts/phase14_fd.py', 'performance/scripts/phase14_dual.py',
               'performance/scripts/phase14_dual_sampling.py', 'performance/scripts/phase14_campaign.py',
               'performance/scripts/run_phase14.py', 'performance/tests/test_phase14_fd.py',
               'docs/phase14_fd_resume_design.md'}
    changed = env.load.run(['git', 'diff', '--name-only', q['fingerprint']['controlHead'], 'HEAD']).stdout.decode().splitlines()
    if any(name not in allowed and not name.startswith(('docs/', 'performance/tests/')) for name in changed):
        raise ValueError('unqualified workload or deployment source change')
    if changed != d['sourceChanges']:
        raise ValueError('source change attestation differs')
    for name in ('g0', 'smoke'):
        ref = q[name]; verify_hashes(ref['root'], ref['hashes']); verify_referenced_runs(ref['root'], name)
    ref = q['initQualification']; verify_hashes(ref['root'], ref['hashes'])
    init = json.loads((Path(ref['root']) / 'init-qualification.json').read_text())
    if init['status'] != 'pass' or init['faultFixture'] or len(init['runs']) != 2:
        raise ValueError('original cold initialization invalid')
    for row in init['runs']:
        verify_hashes(row['root'], row['hashes'])
        cold = json.loads((Path(row['root']) / 'init-only.json').read_text())
        if cold['fingerprint'] != q['fingerprint'] or cold['status'] != 'pass':
            raise ValueError('original cold source differs')
    verify_hashes(d['checks']['root'], d['checks']['hashes'])
    validate_limits(d['backendFd'])
    if immediate:
        fresh = preflight(env)
        if not fresh['passed'] or fresh['diskFreeBytes']['load'] < q['longestScenarioDiskBudgetBytes']:
            raise ValueError('FD immediate preflight failed')
    return q
