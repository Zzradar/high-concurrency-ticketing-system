#!/usr/bin/env python3
"""Bounded Phase10B-3 calibration; operates only on the existing Performance stack."""
import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import time
import uuid

import diagnose_seat_map as diagnosis
import performance_evidence as evidence
import run_k6

OUTCOMES = ('success', 'timeout', 'error', 'parse_error')


def outcome_delta(before, after):
    result = {}
    for outcome in OUTCOMES:
        key = f'ticketing_seat_map_redis_lookup_total{{outcome="{outcome}"}}'
        if key not in before or key not in after:
            raise RuntimeError(f'missing outcome metric: {outcome}')
        result[outcome] = after[key] - before[key]
        if result[outcome] < 0:
            raise RuntimeError('counter reset during calibration')
    return result


def memory(sample):
    raw = sample['backendProcessAndCgroup']
    rss = re.search(r'^VmRSS:\s+(\d+) kB', raw, re.M)
    current = re.search(r'^([0-9]+)$', raw, re.M)
    inactive = re.search(r'^inactive_file (\d+)$', raw, re.M)
    if not all((rss, current, inactive)):
        raise RuntimeError('cannot determine backend memory safety')
    return {'rssBytes': int(rss[1]) * 1024,
            'workingSetBytes': max(0, int(current[1]) - int(inactive[1]))}


def check_safety(sample):
    if memory(sample)['workingSetBytes'] >= 3 * 1024 ** 3:
        raise RuntimeError('backend working set reached conservative 3 GiB stop line')
    health = run_k6.http_json(run_k6.BACKEND_URL + '/health')
    if health.get('status') != 'ok' or health.get('database') != 'up':
        raise RuntimeError('backend unhealthy')
    ping = evidence.command(run_k6.compose_command('exec', '-T', 'redis', 'redis-cli', 'PING'))
    if ping.strip() != 'PONG':
        raise RuntimeError('Redis unhealthy')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rate', type=int, choices=(10, 30, 60), required=True)
    parser.add_argument('--duration', type=int, choices=(15, 30), default=15)
    parser.add_argument('--density', type=int, choices=(0, 90), default=0)
    parser.add_argument('--encoding', choices=('identity', 'gzip'), default='identity')
    parser.add_argument('--drain-seconds', type=int, choices=(0, 180), default=0)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    token = uuid.uuid4().hex[:8]
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-seat-calibration-{args.rate}-{args.density}-{args.encoding}-{token}'
    root = run_k6.RESULTS_ROOT / name
    root.mkdir(parents=True, exist_ok=False)
    container = f'ticketing-phase10a-k6-{token}'
    process = None
    manifest = {'runId': name, 'shortRunToken': token, 'arguments': vars(args),
                'preallocatedVUs': 700, 'jsonSerialize': 'not directly measured in production-equivalent path',
                'bytesScope': 'separate out-of-load HTTP probes; no early getBody',
                'metricsSnapshotQuietSeconds': 6, 'displayValidation': 'every response' if args.density else 'preflight only',
                'gitHead': run_k6.run_command(['git', 'rev-parse', 'HEAD']).stdout.strip()}
    evidence.write_json(root / 'run-manifest.json', manifest)
    try:
        if args.prepare:
            diagnosis.prepare_profile(5000, root)
        dataset = run_k6.read_json(run_k6.GENERATED_ROOT / 'dataset.json')
        seats = run_k6.read_json(run_k6.GENERATED_ROOT / 'workload-seats.json')
        session = dataset['seatMapSessionId']
        # Scope and formal-state checks precede fixture mutation.
        if not session.startswith('perf-session-'):
            raise RuntimeError('not a Performance session')
        formal = evidence.psql(f"SELECT status,count(*) FROM session_seats WHERE session_id='{session}' GROUP BY status ORDER BY status;").strip()
        if formal != 'AVAILABLE\t5000':
            raise RuntimeError(f'unexpected formal inventory: {formal}')
        manifest['formalInventoryBefore'] = formal
        manifest['fixture'] = run_k6.prepare_seat_map_fixture(seats, session, args.density, 600, f'fixture-{token}')
        evidence.write_json(root / 'gzip.json', diagnosis.gzip_probe(session))
        # PromExporter caches for 5s: quiet snapshots avoid stale boundary counts.
        time.sleep(6)
        baseline = diagnosis.sample()
        check_safety(baseline)
        if baseline['httpInFlight'] != 0:
            raise RuntimeError('existing in-flight requests')
        evidence.write_json(root / 'baseline.json', baseline)
        before = diagnosis.metrics()
        outcome_delta(before, before)
        evidence.write_json(root / 'metrics-before.json', before)
        evidence.reset_statement_stats()
        environment = {'RUN_ID': name, 'SHORT_RUN_TOKEN': token, 'BASE_URL': 'http://backend:8080',
                       'MODE': 'steady', 'RATE': str(args.rate), 'DURATION': f'{args.duration}s',
                       'PREALLOCATED_VUS': '700', 'SEAT_MAP_ENCODING': args.encoding,
                       'EXPECTED_HELD': str(manifest['fixture']['heldCount'])}
        command = run_k6.compose_command('--profile', 'load', 'run', '--rm', '--no-deps', '--name', container)
        for key, value in environment.items():
            command += ['-e', f'{key}={value}']
        command += ['k6', 'run', '-o', 'experimental-prometheus-rw', '--tag', f'testid={name}',
                    '/scripts/diagnostics/seat-map-calibration.js']
        manifest['command'] = command
        manifest['startEpoch'] = time.time()
        with (root / 'console.log').open('w', encoding='utf-8') as console, (root / 'samples.jsonl').open('w', encoding='utf-8') as samples:
            process = subprocess.Popen(command, stdout=console, stderr=subprocess.STDOUT, cwd=run_k6.REPO_ROOT)
            finished = None
            while True:
                current = diagnosis.sample()
                samples.write(json.dumps(current) + '\n'); samples.flush()
                check_safety(current)
                if process.poll() is not None:
                    if finished is None:
                        finished = time.time()
                        print(f'k6 exit={process.returncode}; observing drain={args.drain_seconds}s', flush=True)
                    if time.time() - finished >= args.drain_seconds:
                        break
                time.sleep(1)
        manifest['runnerFinishedEpoch'] = finished
        manifest['runnerExit'] = process.returncode
        time.sleep(6)
        after = diagnosis.metrics()
        evidence.write_json(root / 'metrics-after.json', after)
        evidence.write_json(root / 'stages.json', diagnosis.stage_summary(before, after))
        manifest['redisOutcomes'] = outcome_delta(before, after)
        manifest['finalInFlight'] = after.get('ticketing_seat_map_requests_in_flight')
        evidence.write_json(root / 'final.json', diagnosis.sample())
        manifest['formalInventoryAfter'] = evidence.psql(f"SELECT status,count(*) FROM session_seats WHERE session_id='{session}' GROUP BY status ORDER BY status;").strip()
        evidence.collect_postgres(root)
        evidence.collect_redis(root, 'after')
        evidence.collect_docker_stats(root)
        diagnosis.collect_run_resources(root, root, manifest['startEpoch'], time.time())
        verifier = run_k6.run_command([sys.executable, str(run_k6.VERIFIER)], check=False)
        (root / 'verifier.txt').write_text(verifier.stdout + verifier.stderr, encoding='utf-8')
        manifest['verifierExit'] = verifier.returncode
        summary = run_k6.read_json(root / 'business-summary.json')
        manifest['business'] = summary
        if process.returncode or verifier.returncode or any(summary[k] for k in ('dropped_iterations', 'system_error', 'unexpected')):
            raise RuntimeError('stop condition: k6 / correctness / generator failure')
        if manifest['finalInFlight'] != 0 or manifest['formalInventoryAfter'] != formal:
            raise RuntimeError('stop condition: not drained or formal inventory changed')
        manifest['result'] = 'completed; inspect display degradation separately'
        print(f'Evidence: {root}', flush=True)
        return 0
    except Exception as error:
        manifest['error'] = str(error)
        if process is not None and process.poll() is None:
            # Stop only this run's named generator; never restart backend or delete volumes.
            stopped = run_k6.run_command(['docker', 'stop', container], check=False)
            manifest['generatorStopExit'] = stopped.returncode
        print(f'[STOP] {error}; evidence={root}', file=sys.stderr, flush=True)
        return 1
    finally:
        manifest['endEpoch'] = time.time()
        evidence.write_json(root / 'run-manifest.json', manifest)


if __name__ == '__main__':
    raise SystemExit(main())
