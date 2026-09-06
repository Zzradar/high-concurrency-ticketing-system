#!/usr/bin/env python3
"""Sanitized explicit-run comparison; never glob historical calibration into a new experiment."""
import argparse
import json
import re

import diagnose_seat_map as diagnosis
import run_k6
from summarize_seat_map_calibration import read, summarize


def histogram_delta(before, after, name):
    buckets = []
    for key, value in after.items():
        if key.startswith(name + '_bucket{'):
            upper = float(re.search(r'le="([^"]+)"', key)[1])
            if key not in before or value < before[key]:
                raise ValueError('missing baseline or reset compute histogram')
            buckets.append((upper, value - before[key]))
    if not buckets:
        raise ValueError('missing compute histogram')
    return {'samples': max(value for _, value in buckets),
            **{name: diagnosis.quantile(buckets, fraction) for name, fraction in
               (('p50Seconds', .5), ('p95Seconds', .95), ('p99Seconds', .99))}}


def summarize_run(phase, run_id, container_id):
    if phase not in ('before', 'workers2', 'workers4') or not re.fullmatch(r'[a-zA-Z0-9-]+', run_id):
        raise ValueError('invalid explicit experiment run')
    root = run_k6.RESULTS_ROOT / run_id
    result = summarize(root, container_id)
    result.update({'phase': phase, 'backendContainerId': container_id})
    manifest = read(root / 'run-manifest.json')
    if result.get('incompleteOrFailed'):
        # Preserve failure, not a fabricated successful run. Early runner stop
        # may omit verifier/final fields; their absence must stay explicit.
        result.update({key: manifest[key] for key in ('arguments', 'redisOutcomes', 'runnerExit', 'finalInFlight')
                       if key in manifest})
        result['business'] = read(root / 'business-summary.json')
        result['stages'] = read(root / 'stages.json')
    if phase != 'before':
        if manifest['backendContainerId'] != container_id or phase != 'workers' + str(manifest['compute']['workers']):
            raise ValueError('manifest/container/worker mismatch')
        before, after = read(root / 'metrics-before.json'), read(root / 'metrics-after.json')
        samples = [json.loads(line) for line in (root / 'samples.jsonl').read_text(encoding='utf-8').splitlines()]
        final_path = root / 'final.json'
        if not final_path.exists():
            final_path = root / 'supplemental-final.json'
            result['finalSampleScope'] = 'later read-only post-failure check; not original runner boundary'
        samples = [read(root / 'baseline.json'), *samples, read(final_path)]
        result['compute'] = {**manifest['compute'],
            'queueWait': histogram_delta(before, after, 'ticketing_seat_map_compute_queue_wait_seconds'),
            'execution': histogram_delta(before, after, 'ticketing_seat_map_compute_execution_seconds'),
            'timeline': [{ 'epoch': sample['epoch'],
                          'depth': sample['seatMapCompute']['ticketing_seat_map_compute_queue_depth'],
                          'active': sample['seatMapCompute']['ticketing_seat_map_compute_active_workers']}
                         for sample in samples]}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', nargs=3, action='append', required=True,
                        metavar=('PHASE', 'RUN_ID', 'CONTAINER_ID'))
    args = parser.parse_args()
    print(json.dumps({'runs': [summarize_run(*run) for run in args.run]}, indent=2))
