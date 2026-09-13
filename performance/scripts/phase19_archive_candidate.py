"""Named candidate diagnostics and qualification; preserve original source hashes."""
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/'performance/experiments/phase19-global-polling-mixed-load'
PRIVATE=Path(tempfile.gettempdir())


def digest(data):return hashlib.sha256(data).hexdigest()


def redact(text):
    for value,label in [(str(ROOT),'<PHASE19_WORKTREE>'),(str(PRIVATE),'<PRIVATE_TEMP>')]:
        text=text.replace(value.replace('\\','\\\\'),label).replace(value,label)
    return re.sub(r'ws://127\.0\.0\.1:\d+/devtools/browser/[\w-]+','<DEVTOOLS_ENDPOINT>',text)


def archive(source,target,allowed):
    files={}
    if not source.exists():return
    for path in source.iterdir():
        if not path.is_file() or path.name not in allowed:continue
        raw=path.read_bytes()
        encoded=redact(raw.decode('utf-8').replace('\r\n','\n')).encode()
        destination=target/path.name
        if destination.exists() and destination.read_bytes()!=encoded:raise ValueError('Refuse altered prior point '+str(destination))
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(encoded)
        files[path.name]={'sourceSha256':digest(raw),'sourceBytes':len(raw),'archivedSha256':digest(encoded),'archivedBytes':len(encoded)}
    (target/'archive-manifest.json').write_bytes((json.dumps({'source':'<PRIVATE_TEMP>/'+source.name,'normalization':'UTF-8 newline normalization and private-path/DevTools redaction','files':files},indent=2)+'\n').encode())


def index():
    files={str(p.relative_to(EVIDENCE)).replace('\\','/'):{'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size}
        for p in EVIDENCE.rglob('*') if p.is_file() and p.name!='EVIDENCE_SHA256.json' and '__pycache__' not in p.parts}
    (EVIDENCE/'EVIDENCE_SHA256.json').write_bytes((json.dumps({'scope':'Phase19 evolving evidence index; delivery status remains explicit in reports','files':files},indent=2)+'\n').encode())


def main():
    allowed={'result.json','identity.json','k6-summary.json','k6.log','stub.log','resource-samples.json','aggregate.json','resources.json','system-observations.json',
        'verifier-before.json','verifier-after.json','inventory-before.json','inventory-after.json','cleanup.json','control-probes.json','browser.json','browser.log','observer-timeline.json'}
    names=['phase19-journeys-smoke-r1','phase19-open-counter-smoke-r1','phase19-open-propagation-smoke-r1','phase19-layout10k-smoke-r1']
    names += ['phase19-browser-payment-smoke-r'+str(n) for n in range(1,5)]
    names += ['phase19-browser-submitting-smoke-r1']
    names += ['phase19-browser-'+scene+'-smoke-r2' for scene in ['submitting','refund','seat','events','panel','logout']]
    names += ['phase19-browser-'+scene+'-terminal-smoke-r'+str(n) for scene in ['payment','submitting','refund'] for n in [1,2]]
    for name in names:
        archive(PRIVATE/name,EVIDENCE/'diagnostics/protocol-candidate'/name,allowed)
        if (PRIVATE/name/'propagation').exists():archive(PRIVATE/name/'propagation',EVIDENCE/'diagnostics/protocol-candidate'/name/'propagation',allowed)
    for vus in [100,250,500,1000]:
        archive(PRIVATE/f'phase19-calibration-{vus}-r3',EVIDENCE/'generator-calibration/candidate-2g'/str(vus),allowed)
    for vus in [100,250,500,1000,2000]:
        archive(PRIVATE/f'phase19-calibration-4g-{vus}-r1',EVIDENCE/'generator-calibration/candidate-4g'/str(vus),allowed)
    index()


if __name__=='__main__':main()
