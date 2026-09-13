"""Read-only final evidence integrity audit; never repairs or reclassifies a run."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from phase19_polling_manifest import build

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'performance/experiments/phase19-global-polling-mixed-load'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    return json.loads(gzip.decompress(Path(str(path)+'.gz').read_bytes()))

def valid_capacity(result):
    if result.get('valid') is not True or result.get('diagnostic') is not False:
        raise ValueError('Invalid or diagnostic point cannot be delivered as stable')
    if result.get('exitCode') != 0 or result.get('metricSummaryAvailable') is not True:
        raise ValueError('Missing successful metric summary')
    if any(result.get(k) != 0 for k in ['interruptedIterations','droppedIterations']):
        raise ValueError('Incomplete workload')
    counts = [result[k] for k in ['startedIterations','completedBusinessIterations','k6CompletedIterations']]
    if not counts[0] or len(set(counts)) != 1:
        raise ValueError('Iteration conservation failed')
    a = result['accounting']
    if a['errors'] or a['startedByKind'] != a['completedByKind'] or sum(a['startedByKind'].values()) != counts[0]:
        raise ValueError('Business conservation failed')
    if result.get('observerErrors') or result.get('propagationPassed', True) is not True:
        raise ValueError('Propagation failed')

def verifier(record):
    if record.get('passed') is not True or not record.get('checks') or any(record['checks'].values()):
        raise ValueError('Verifier has violations or no checks')

def index_matches(folder):
    index = read(folder/'EVIDENCE_SHA256.json')['files']
    actual = {p.relative_to(folder).as_posix():p for p in folder.rglob('*')
              if p.is_file() and p.name != 'EVIDENCE_SHA256.json' and '__pycache__' not in p.parts}
    if set(actual) != set(index): raise ValueError('Evidence index omissions or stale paths')
    for name,p in actual.items():
        if sha(p) != index[name]['sha256'] or p.stat().st_size != index[name]['bytes']:
            raise ValueError('Evidence bytes changed: '+name)
    return len(actual)

def main():
    f = read(EVIDENCE/'protocol-sha256.json')
    if f['files'] != {p.name:sha(p) for p in (EVIDENCE/'protocol').iterdir() if p.is_file()}:
        raise ValueError('Frozen protocol drift')
    for revision in ['baseline','after']:
        if build(EVIDENCE,revision) != read(EVIDENCE/('polling-'+revision)/'manifest.json'):
            raise ValueError('Browser manifest drift')
    stable = ['closed-100','closed-500','closed-1000','closed-2000','closed-2000-10m',
              'open-precheck','open-L1','open-L2','open-L3','journeys-5000',
              'hotspot-100','hotspot-500','hotspot-1000']
    for name in stable:
        point = EVIDENCE/'capacity-thousands/baseline'/name
        result = read(point/'result.json'); valid_capacity(result)
        identity = read(point/'identity.json')
        if identity['protocolSha256'] != f['files']: raise ValueError('Capacity protocol drift')
        if identity['generatorLimits']['memoryBytes'] != 4*1024**3: raise ValueError('Generator identity drift')
        for phase in ['before','after']: verifier(read(point/('verifier-'+phase+'.json')))
        if name.startswith('hotspot-') and (result['hotspotWinners'] != 1 or result['controlProbeFailures'] != 0):
            raise ValueError('Hotspot correctness failed')
    unstable = read(EVIDENCE/'capacity-thousands/baseline/closed-3000/result.json')
    if unstable['valid'] is not False: raise ValueError('First unstable point lost')
    layout = read(EVIDENCE/'capacity-thousands/baseline/layout-10000/result.json')
    if layout['passed'] is not True or layout['mismatches'] != 0 or layout['seats'] != 10000:
        raise ValueError('Layout incomplete')
    scale = read(EVIDENCE/'scale-estimate/estimate.json')
    if scale['actualTensOfThousandsExecuted'] is not False or any(t['status'] != 'UNSAFE' for t in scale['targets']):
        raise ValueError('Scale claims changed')
    git = lambda *a:subprocess.check_output(['git','-C',str(ROOT),*a],text=True).strip()
    for path in ['backend/src','backend/config','backend/db/migrations']:
        if git('rev-parse','HEAD:'+path) != f['productionTrees'][path] or git('diff','HEAD','--',path):
            raise ValueError('Backend production changed: '+path)
    prior = read(EVIDENCE/'stage0/manifest.json')['priorEvidenceTrees']
    for name,tree in prior.items():
        path = 'performance/experiments/'+name
        if git('rev-parse','HEAD:'+path) != tree or git('diff','HEAD','--',path):
            raise ValueError('Historical evidence changed: '+name)
    print(json.dumps({'passed':True,'stableCapacityPoints':len(stable),'browserScenesPerGroup':7,
                      'indexedFiles':index_matches(EVIDENCE),'protocolSha256':sha(EVIDENCE/'protocol-sha256.json')}))

if __name__ == '__main__': main()
