"""Package browser point identities and enforce the requested visibility windows."""
import argparse
import json
from pathlib import Path
from phase19_archive_candidate import digest, EVIDENCE, index

SCENES = ('events', 'panel', 'seat', 'payment', 'refund', 'submitting', 'logout')


def validate_browser(point, revision, files):
    if point.get('diagnostic') is not False or point.get('passed') is not True:
        raise ValueError('Only successful formal browser points can enter A/B')
    if point.get('revision') != revision or point.get('protocol') != files:
        raise ValueError('Browser identity or frozen protocol mismatch')
    phases = point['phases']
    if [p['name'] for p in phases] != ['visible', 'hidden', 'restored']:
        raise ValueError('Incomplete visibility sequence')
    if any(p['durationMs'] < minimum for p, minimum in zip(phases, [60000, 91000, 30000])):
        raise ValueError('Short browser observation window')
    changes = [v for v in point['visibility'] if v['type'] == 'visibilitychange']
    # This is an integrity check of recorded native events, not a timer override.
    if len(changes) != 2:
        raise ValueError('Extra native visibility transitions contaminate the planned windows')
    for change, phase, expected in zip(changes, phases[1:], [True, False]):
        if change.get('trusted') is not True or change['hidden'] is not expected:
            raise ValueError('Native visibility evidence missing')
        if not 0 <= change['epochMs'] - phase['activationEpochMs'] <= 1000:
            raise ValueError('Visibility transition is outside its scripted activation')
    checks = point['checks']
    if not checks['terminalObserved'] or (checks['readsAfterTerminalSettled'] or 0) != 0:
        raise ValueError('Terminal recovery did not settle')
    if revision == 'after' and (checks['hiddenNewReads'] or checks['logoutNewReads']
            or any(n > 1 for n in checks['maxInflight'].values())
            or any(n > 1 for n in checks['restoredImmediateCounts'].values())):
        raise ValueError('After polling hard gate failed')


def build(evidence, revision):
    frozen_raw = (evidence / 'protocol-sha256.json').read_bytes()
    frozen = json.loads(frozen_raw)
    folder = evidence / ('polling-' + revision)
    points = {}
    artifact_identity = None
    production_tree = None
    for scene in SCENES:
        raw = (folder / scene / 'browser.json').read_bytes()
        point = json.loads(raw)
        validate_browser(point, revision, frozen['files'])
        if point['scene'] != scene: raise ValueError('Scene identity mismatch')
        if artifact_identity is not None and point['artifacts'] != artifact_identity:
            raise ValueError('Served build changed within one browser group')
        if production_tree is not None and point['frontendTree'] != production_tree:
            raise ValueError('Frontend source changed within one browser group')
        artifact_identity = point['artifacts']; production_tree = point['frontendTree']
        points[scene] = {'path': f'polling-{revision}/{scene}/browser.json',
                         'sha256': digest(raw), 'sourceCommit': point['sourceCommit'],
                         'startedUtc': point['startedUtc'], 'endedUtc': point['endedUtc'],
                         'checks': point['checks']}
    if revision == 'baseline' and production_tree != frozen['productionTrees']['frontend/src']:
        raise ValueError('Baseline is not the frozen production source')
    return {'revision': revision, 'protocolSha256': digest(frozen_raw),
            'frontendTree': production_tree, 'artifacts': artifact_identity,
            'points': points, 'status': 'COMPLETE_FORMAL_BROWSER_GROUP'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('revision', choices=['baseline', 'after'])
    args = parser.parse_args()
    manifest = build(EVIDENCE, args.revision)
    target = EVIDENCE / ('polling-' + args.revision) / 'manifest.json'
    if target.exists(): raise ValueError('Refuse replacing a completed browser group manifest')
    target.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    index()
