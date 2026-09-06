#!/usr/bin/env python3
"""Print sanitized calibration evidence from completed runs; no database operations."""
import json
import argparse
import re

from calibrate_seat_map import memory
import run_k6


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def summarize(root, backend_container_id):
    if not re.fullmatch(r'[a-f0-9]{64}', backend_container_id):
        raise ValueError('exact inspected Backend container ID required')
    manifest = read(root / 'run-manifest.json')
    if 'error' in manifest or manifest.get('runnerExit') != 0:
        return {'runId': root.name, 'incompleteOrFailed': True, 'error': manifest.get('error')}
    baseline, final = read(root / 'baseline.json'), read(root / 'final.json')
    samples = [json.loads(line) for line in (root / 'samples.jsonl').read_text().splitlines()]
    all_samples = [baseline, *samples, final]
    timeline = [{'epoch': s['epoch'], 'inFlight': s['seatMapInFlight'], **memory(s),
                 'redisUsedMemoryBytes': s['redisMemory']['used_memory'],
                 'sumClientOmem': sum(int(c.get('omem', 0)) for c in s['clients']),
                 'postgresConnections': s['postgresConnections']} for s in all_samples]
    metrics = read(root / 'k6-summary.json')['metrics']
    resources = read(root / 'scoped-resources.json')
    resource_summary = {}
    for service, queries in resources.items():
        resource_summary[service] = {}
        for key, response in queries.items():
            series = response.get('data', {}).get('result', [])
            observed = len(series)
            if service == 'backend':
                series = [row for row in series if row['metric'].get('id') == '/docker/' + backend_container_id]
            values = [float(v) for row in series for _, v in row.get('values', [])]
            resource_summary[service][key] = {'max': max(values) if values else None,
                                            'seriesCount': len(series), 'excludedSeries': observed - len(series)}
    sql = next(line.split('\t', 7) for line in (root / 'postgres-top-sql.tsv').read_text().splitlines()
               if 'JOIN seats AS seat' in line)
    clients = [c for s in all_samples for c in s['clients']]
    result = {key: manifest[key] for key in ('runId', 'arguments', 'startEpoch', 'runnerFinishedEpoch', 'endEpoch',
                                            'redisOutcomes', 'verifierExit', 'runnerExit', 'finalInFlight',
                                            'formalInventoryBefore', 'formalInventoryAfter', 'fixture', 'business')}
    result.update({
        'gzip': read(root / 'gzip.json'), 'stages': read(root / 'stages.json'),
        'http': {key: metrics[key]['values'] for key in ('http_req_duration', 'http_req_waiting', 'http_req_receiving', 'data_received')},
        'display': {key: value['values'] for key, value in metrics.items() if key.startswith('ticketing_display_')},
        'resources': resource_summary, 'peakInFlight': max(s['inFlight'] for s in timeline),
        'memory': {key: {'before': timeline[0][key], 'peak': max(s[key] for s in timeline), 'after': timeline[-1][key]}
                   for key in ('rssBytes', 'workingSetBytes', 'redisUsedMemoryBytes')},
        'clientMaxOmem': max(int(c.get('omem', 0)) for c in clients),
        'clientMaxOll': max(int(c.get('oll', 0)) for c in clients),
        'largestClient': max(clients, key=lambda c: int(c.get('omem', 0))),
        'postgres': {'calls': int(sql[0]), 'meanExecMs': float(sql[2]),
                     'connectionsMax': max(s['postgresConnections'] for s in timeline)},
        'samples': len(samples),
    })
    if manifest['arguments']['drain_seconds']:
        result['timeline'] = timeline
        # Observational timestamp only: exporter is cached and samples are discrete.
        active = [s['epoch'] for s in timeline if s['inFlight'] > 0]
        result['firstObservedZeroAfterLastActive'] = next((s['epoch'] for s in timeline if active and s['epoch'] > max(active) and s['inFlight'] == 0), None)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-container-id', required=True)
    args = parser.parse_args()
    print(json.dumps({'backendContainerId': args.backend_container_id,
                      'runs': [summarize(root, args.backend_container_id)
                               for root in sorted(run_k6.RESULTS_ROOT.glob('*-seat-calibration-*'))]}, indent=2))
