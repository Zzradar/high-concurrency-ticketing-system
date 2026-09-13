"""Archive named, unfrozen protocol diagnostics without private raw fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/'performance/experiments/phase19-global-polling-mixed-load'
PRIVATE=Path(tempfile.gettempdir())
RUNS=['phase19-open-smoke-r1','phase19-open-smoke-r2','phase19-open-smoke-r3',
      'phase19-hotspot-smoke-100-r1','phase19-propagation-smoke-r1','phase19-propagation-smoke-r2']
ALLOWED={'result.json','identity.json','k6-summary.json','k6.log','aggregate.json','resources.json',
         'system-observations.json','verifier-before.json','verifier-after.json','cleanup.json',
         'control-probes.json','observer-timeline.json'}


def redact(text):
    for path,label in [(str(ROOT),'<PHASE19_WORKTREE>'),(str(PRIVATE),'<PRIVATE_TEMP>')]:
        text=text.replace(path.replace('\\','\\\\'),label).replace(path,label)
    return text


def write_once(target,data):
    if target.exists() and target.read_bytes()!=data:
        raise ValueError('Refuse replacing retained diagnostic '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)


def main():
    for name in RUNS:
        source=PRIVATE/name
        for path in source.iterdir():
            if path.name in ALLOWED:
                write_once(EVIDENCE/'diagnostics/protocol-development'/name/path.name,redact(path.read_text(encoding='utf-8')).encode())
    write_once(EVIDENCE/'diagnostics/protocol-development/python-tests.log',redact((PRIVATE/'phase19-python-protocol.log').read_text(encoding='utf-8')).encode())
    index={str(p.relative_to(EVIDENCE)).replace('\\','/'):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
           for p in EVIDENCE.rglob('*') if p.is_file() and p.name!='EVIDENCE_SHA256.json' and '__pycache__' not in p.parts}
    (EVIDENCE/'EVIDENCE_SHA256.json').write_bytes((json.dumps({'scope':'Stage0 and unfrozen protocol development; not final Phase19 delivery','files':index},indent=2)+'\n').encode())


if __name__=='__main__':main()
