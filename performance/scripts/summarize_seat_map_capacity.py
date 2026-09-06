#!/usr/bin/env python3
"""Read explicit run IDs, retaining failed gates and complete time trends."""
import argparse
import json
import math
import re

from calibrate_seat_map import memory, outcome_delta
import run_k6
from summarize_seat_map_calibration import read
from summarize_seat_map_offload import histogram_delta


def interval_histogram(previous, current):
    try:
        return histogram_delta(previous, current, 'ticketing_seat_map_compute_queue_wait_seconds')
    except ValueError as error:
        # Different HTTP loops can return differently aged exporter caches.
        # Do not clamp negative deltas or invent a valid interval quantile.
        return {'unavailable': str(error), 'scope': 'nonmonotonic/missing sampled buckets; raw artifacts retained'}


def summarize(run_id):
    if not re.fullmatch(r'[a-zA-Z0-9-]+', run_id): raise ValueError('explicit safe run ID required')
    root = run_k6.RESULTS_ROOT / run_id
    manifest = read(root / 'run-manifest.json')
    result = {key: value for key, value in manifest.items() if key not in ('command', 'auth')}
    if 'error' in manifest or 'endEpoch' not in manifest:
        result['incomplete'] = True
        return result
    before, after = read(root / 'metrics-before.json'), read(root / 'metrics-after.json')
    samples = [read(root / 'baseline.json'), *[json.loads(line) for line in
                (root / 'samples.jsonl').read_text().splitlines()], read(root / 'final.json')]
    result['timeline'] = []
    previous = before
    for sample in samples:
        compute = sample['seatMapCompute']
        interval = interval_histogram(previous, compute)
        result['timeline'].append({'epoch': sample['epoch'], **memory(sample),
            'queue': compute['ticketing_seat_map_compute_queue_depth'],
            'active': compute['ticketing_seat_map_compute_active_workers'],
            'inFlight': sample['seatMapInFlight'], 'httpInFlight': sample['httpInFlight'],
            'queueWaitInterval': interval,
            'redisOutcomesCumulativeDelta': outcome_delta(before, {**before, **sample['redisOutcomes']}),
            'redisUsedMemory': sample['redisMemory']['used_memory'],
            'maxOmem': max(int(c.get('omem', 0)) for c in sample['clients']),
            'maxOll': max(int(c.get('oll', 0)) for c in sample['clients']),
            'postgresConnections': sample['postgresConnections']})
        if 'unavailable' not in interval:
            previous = compute
    result['compute'].update({key: histogram_delta(before, after, 'ticketing_seat_map_compute_' + suffix)
                              for key, suffix in [('queueWait', 'queue_wait_seconds'), ('execution', 'execution_seconds')]})
    result['stages'] = read(root / 'stages.json')
    metrics = read(root / 'k6-summary.json')['metrics']
    result['http'] = {key: value['values'] for key, value in metrics.items()
                      if key.startswith(('http_req_', 'ticketing_capacity_', 'ticketing_display_', 'ticketing_seat_map_503'))
                      or key in ('data_received', 'iterations', 'dropped_iterations', 'vus', 'vus_max')}
    result['httpP95Trend'] = read(root / 'http-p95-trend.json')['data']['result']
    result['resources'] = {}
    for service, queries in read(root / 'scoped-resources.json').items():
        result['resources'][service] = {}
        for key, payload in queries.items():
            series = payload['data']['result']
            if service == 'backend':
                series = [row for row in series if row['metric'].get('id') == '/docker/' + manifest['identityBefore']['containerId']]
            values = [float(v) for row in series for _, v in row.get('values', []) if math.isfinite(float(v))]
            result['resources'][service][key] = {'max': max(values) if values else None, 'series': series}
    result['postgres'] = read(root / 'postgres-top-sql.json')
    result['gzip'] = read(root / 'gzip.json')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compact', action='store_true')
    parser.add_argument('run_ids', nargs='+')
    args = parser.parse_args()
    print(json.dumps({'runs': [summarize(run_id) for run_id in args.run_ids]}, indent=None if args.compact else 2))
