"""Lossless packaging only: never changes measurements or classifies pass/fail."""
import argparse
import gzip
import json
from pathlib import Path
from phase19_archive_candidate import digest, redact, EVIDENCE, index

ALLOWED = {
    'result.json', 'identity.json', 'k6-summary.json', 'k6.log', 'aggregate.json',
    'resources.json', 'system-observations.json', 'verifier-before.json',
    'verifier-after.json', 'inventory-before.json', 'inventory-after.json',
    'cleanup.json', 'control-probes.json', 'browser.json', 'browser.log',
    'observer-timeline.json',
}


def package(source, target):
    if target.exists():
        raise ValueError('Archive destination must be new')
    if not source.is_dir():
        raise ValueError('Missing point directory')
    completed = source / ('browser.json' if (source / 'browser.json').exists() else 'result.json')
    if not completed.exists():
        raise ValueError('No completed point result; preserve incomplete diagnostics separately')
    record = json.loads(completed.read_text(encoding='utf-8'))
    if not isinstance(record.get('endedUtc'), str):
        raise ValueError('Point is still running; no completion timestamp')
    files = {}
    pending = {}
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if not path.is_file() or path.name not in ALLOWED:
            continue
        if len(relative.parts) > 1 and relative.parts[0] != 'propagation':
            continue
        raw = path.read_bytes()
        normalized = redact(raw.decode('utf-8').replace('\r\n', '\n')).encode()
        name = relative.as_posix()
        stored_name = name + '.gz' if len(normalized) > 1_000_000 else name
        stored = gzip.compress(normalized, mtime=0) if stored_name.endswith('.gz') else normalized
        pending[stored_name] = stored
        files[name] = {'sourceSha256': digest(raw), 'sourceBytes': len(raw),
                       'normalizedSha256': digest(normalized), 'normalizedBytes': len(normalized),
                       'storedAs': stored_name, 'storedSha256': digest(stored), 'storedBytes': len(stored)}
    raw_points = source / 'k6-points.jsonl'
    if not raw_points.exists(): raw_points = source / 'k6-points.jsonl.gz'
    private = None
    if raw_points.exists():
        raw = raw_points.read_bytes()
        private = {'path': '<PRIVATE_TEMP>/' + source.name + '/' + raw_points.name,
                   'sha256': digest(raw), 'bytes': len(raw)}
        if record.get('rawPointsSha256') != private['sha256'] or record.get('rawPointsBytes') != private['bytes']:
            raise ValueError('Raw metric hash/length differs from completed result')
    manifest = {'source': '<PRIVATE_TEMP>/' + source.name,
                'normalization': 'UTF-8 newline and private-path redaction; gzip is lossless with mtime=0',
                'classification': 'Result fields are preserved verbatim, including invalid outcomes',
                'files': files, 'privateRawPoints': private}
    target.mkdir(parents=True)
    for name, value in pending.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)
    (target / 'archive-manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    destination = (EVIDENCE / args.destination).resolve()
    if not destination.is_relative_to(EVIDENCE.resolve()) or destination == EVIDENCE.resolve():
        raise ValueError('Destination must be a child of Phase19 evidence')
    package(args.source, destination)
    index()
