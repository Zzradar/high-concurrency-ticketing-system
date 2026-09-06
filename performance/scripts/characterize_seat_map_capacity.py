#!/usr/bin/env python3
"""One manually selected, bounded run on the existing isolated Performance stack."""
import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import time
import uuid

import calibrate_seat_map as calibration
import diagnose_seat_map as diagnosis
import performance_evidence as evidence
import run_k6


def validate_config(config):
    custom = config['custom_config']
    if (custom['seat_map_compute_workers'], custom['seat_map_compute_queue_capacity']) != (4, 16):
        raise RuntimeError('capacity characterization requires workers=4 / queue=16')
    if config['db_clients'][0]['number_of_connections'] != 4:
        raise RuntimeError('PostgreSQL pool changed')
    redis = next(item for item in config['redis_clients'] if item['name'] == 'seat_holds')
    if (redis['number_of_connections'], redis['timeout']) != (2, .4):
        raise RuntimeError('seat-hold Redis pool/timeout changed')


def identity():
    container = evidence.command(run_k6.compose_command('ps', '-q', 'backend')).strip()
    inspected = json.loads(evidence.command(['docker', 'inspect', container]))[0]
    if inspected['Config']['Labels']['com.docker.compose.project'] != 'ticketing-phase10a':
        raise RuntimeError('wrong project')
    live = json.loads(evidence.command(run_k6.compose_command(
        'exec', '-T', 'backend', 'cat', '/app/config/config.performance.json')))
    validate_config(live)
    if inspected['Config']['Cmd'] != ['./ticketing_backend', 'config/config.performance.json']:
        raise RuntimeError(f"unexpected runtime command: {inspected['Config']['Cmd']}")
    return {'containerId': container, 'image': inspected['Image'],
            'startedAt': inspected['State']['StartedAt'], 'restartCount': inspected['RestartCount'],
            'workers': 4, 'queueCapacity': 16, 'postgresPool': 4,
            'seatHoldRedisPool': 2, 'redisTimeoutSeconds': .4}


def sample():
    current = diagnosis.sample()
    values = diagnosis.metrics()
    current['redisOutcomes'] = {key: values[key] for key in values
                               if key.startswith('ticketing_seat_map_redis_lookup_total')}
    return current


def count(metrics, name):
    return metrics.get(name, {}).get('values', {}).get('count', 0)


def failures(manifest, metrics):
    """Hard gates only. Time trends still require explicit human review before escalation."""
    reasons = []
    if manifest['runnerExit'] or manifest['verifierExit']:
        reasons.append('runner/verifier failure')
    for key in ('dropped_iterations', 'ticketing_system_error_total', 'ticketing_unexpected_total',
                'ticketing_display_degraded_total', 'ticketing_display_invalid_total', 'ticketing_seat_map_503_total'):
        if count(metrics, key): reasons.append(key)
    for outcome, value in manifest['redisOutcomes'].items():
        if outcome != 'success' and value: reasons.append('redis_' + outcome)
    if manifest['compute']['rejected'] or not manifest['drained']:
        reasons.append('compute rejection/incomplete drain')
    if manifest['formalInventoryBefore'] != manifest['formalInventoryAfter']:
        reasons.append('formal inventory changed')
    for kind, rate in manifest['rates'].items():
        completed = count(metrics, f'ticketing_capacity_{kind}_completed_total')
        if completed < rate * manifest['arguments']['duration']:
            reasons.append(kind + ' target not delivered')
        if completed != count(metrics, f'ticketing_capacity_{kind}_success_total'):
            reasons.append(kind + ' unsuccessful responses')
    if count(metrics, 'ticketing_display_exact_total') != count(metrics, 'ticketing_capacity_seat_completed_total'):
        reasons.append('not every seat response exact')
    return reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rate', type=int, choices=(10, 30, 60, 100, 150, 200, 300, 400, 500, 600), required=True)
    parser.add_argument('--duration', type=int, choices=(15, 300), default=15)
    parser.add_argument('--density', type=int, choices=(0, 90), default=0)
    parser.add_argument('--encoding', choices=('gzip', 'identity'), default='gzip')
    parser.add_argument('--mixed', type=int, choices=(2, 4, 8))
    parser.add_argument('--kind', choices=('seat', 'availability', 'layout', 'page-entry'), default='seat')
    parser.add_argument('--drain-seconds', type=int, choices=(0, 180), default=0)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.mixed and (args.kind != 'availability' or args.rate != 75 * args.mixed or args.encoding != 'gzip'):
        parser.error('mixed requires seat rate=75*multiplier and gzip')
    if args.duration == 300 and args.drain_seconds != 180:
        parser.error('long observation requires 180s drain')
    token = uuid.uuid4().hex[:8]
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-split-{args.kind}-{args.rate}-{args.density}-{token}'
    root = run_k6.RESULTS_ROOT / name
    root.mkdir(parents=True, exist_ok=False)
    container = f'ticketing-phase10a-k6-{token}'
    manifest = {'runId': name, 'shortRunToken': token, 'arguments': vars(args),
                'rates': {'seat': args.rate}, 'displayValidation': 'every pressure response, including 0%',
                'sampling': 'sequential samples; PromExporter 5s cache; resource CPU is 30s rate',
                'preallocatedVUsPerScenario': 700, 'fixtureTtlSeconds': 900,
                'gitHead': evidence.command(['git', 'rev-parse', 'HEAD']).strip()}
    process = None
    evidence.write_json(root / 'run-manifest.json', manifest)
    try:
        manifest['identityBefore'] = identity()
        if args.prepare: diagnosis.prepare_profile(5000, root)
        dataset = run_k6.read_json(run_k6.GENERATED_ROOT / 'dataset.json')
        seats = run_k6.read_json(run_k6.GENERATED_ROOT / 'workload-seats.json')
        session = dataset['seatMapSessionId']
        if not re.fullmatch(r'perf-session-[a-zA-Z0-9-]+', session):
            raise RuntimeError('not a safe Performance session identifier')
        sql = f"SELECT status,count(*) FROM session_seats WHERE session_id='{session}' GROUP BY status ORDER BY status;"
        formal = evidence.psql(sql).strip()
        if formal != 'AVAILABLE\t5000': raise RuntimeError('formal fixture is not AVAILABLE=5000')
        manifest['formalInventoryBefore'] = formal
        manifest['fixture'] = run_k6.prepare_seat_map_fixture(seats, session, args.density, 900, f'fixture-{token}')
        if args.mixed:
            manifest['rates'].update(public=100 * args.mixed, auth=100 * args.mixed)
            manifest['auth'] = run_k6.prepare_auth(argparse.Namespace(auth_mode='warm', auth_pool_size=100),
                                                  run_k6.read_json(run_k6.GENERATED_ROOT / 'sessions.json'))
        endpoint = {'seat': 'seats', 'availability': 'seat-availability',
                    'layout': 'seat-layout', 'page-entry': 'seat-availability'}[args.kind]
        evidence.write_json(root / 'gzip.json', diagnosis.gzip_probe(session, endpoint))
        time.sleep(6)
        baseline = sample()
        calibration.check_safety(baseline)
        if baseline['httpInFlight'] != 0: raise RuntimeError('existing HTTP in-flight')
        evidence.write_json(root / 'baseline.json', baseline)
        before = diagnosis.metrics()
        calibration.outcome_delta(before, before)
        evidence.write_json(root / 'metrics-before.json', before)
        evidence.reset_statement_stats()
        environment = {'RUN_ID': name, 'SHORT_RUN_TOKEN': token, 'BASE_URL': 'http://backend:8080',
                       'MODE': 'steady', 'RATE': str(args.rate), 'DURATION': f'{args.duration}s',
                       'SEAT_MAP_ENCODING': args.encoding, 'EXPECTED_HELD': str(manifest['fixture']['heldCount']),
                       'CAPACITY_KIND': 'mixed' if args.mixed else args.kind,
                       'PUBLIC_RATE': str(manifest['rates'].get('public', 1)),
                       'AUTH_RATE': str(manifest['rates'].get('auth', 1))}
        command = run_k6.compose_command('--profile', 'load', 'run', '--rm', '--no-deps', '--name', container)
        for key, value in environment.items(): command += ['-e', f'{key}={value}']
        command += ['k6', 'run', '-o', 'experimental-prometheus-rw', '--tag', f'testid={name}',
                    '/scripts/diagnostics/post-offload-capacity.js']
        manifest.update(command=command, startEpoch=time.time())
        evidence.write_json(root / 'run-manifest.json', manifest)
        with (root / 'console.log').open('w', encoding='utf-8') as console, (root / 'samples.jsonl').open('w', encoding='utf-8') as output:
            process = subprocess.Popen(command, stdout=console, stderr=subprocess.STDOUT, cwd=run_k6.REPO_ROOT)
            finished = None
            while True:
                current = sample()
                output.write(json.dumps(current) + '\n'); output.flush()
                calibration.check_safety(current)
                if process.poll() is None and time.time() - manifest['startEpoch'] > args.duration + 90:
                    raise RuntimeError('generator exceeded bounded run deadline')
                if args.duration == 300 and process.poll() is None:
                    rejected = 'ticketing_seat_map_compute_submissions_total{outcome="rejected"}'
                    if current['seatMapCompute'][rejected] > before[rejected] or any(
                        value for key, value in calibration.outcome_delta(before, {**before, **current['redisOutcomes']}).items()
                        if key != 'success'):
                        manifest['earlyStop'] = 'long observation saw rejection/Redis failure'
                        evidence.command(['docker', 'stop', container])
                if process.poll() is not None:
                    if finished is None:
                        finished = time.time()
                        print(f'k6 exit={process.returncode}; drain={args.drain_seconds}s', flush=True)
                    if time.time() - finished >= args.drain_seconds: break
                time.sleep(1)
        manifest.update(runnerFinishedEpoch=finished, runnerExit=process.returncode)
        time.sleep(6)
        after = diagnosis.metrics()
        evidence.write_json(root / 'metrics-after.json', after)
        evidence.write_json(root / 'stages.json', diagnosis.stage_summary(before, after))
        manifest['redisOutcomes'] = calibration.outcome_delta(before, after)
        prefix = 'ticketing_seat_map_compute_'
        manifest['compute'] = {outcome: after[prefix + f'submissions_total{{outcome="{outcome}"}}'] - before[prefix + f'submissions_total{{outcome="{outcome}"}}']
                               for outcome in ('accepted', 'rejected')}
        manifest['drained'] = all(after[key] == 0 for key in
                                  (prefix + 'queue_depth', prefix + 'active_workers', 'ticketing_seat_map_requests_in_flight'))
        evidence.write_json(root / 'final.json', sample())
        manifest['formalInventoryAfter'] = evidence.psql(sql).strip()
        manifest['identityAfter'] = identity()
        if manifest['identityBefore'] != manifest['identityAfter']: raise RuntimeError('backend identity changed')
        evidence.collect_postgres(root)
        evidence.collect_redis(root, 'after')
        evidence.collect_docker_stats(root)
        diagnosis.collect_run_resources(root, root, manifest['startEpoch'], time.time())
        series = run_k6.verify_remote_write(name, manifest['startEpoch'])
        evidence.write_json(root / 'remote-write-series.json', series)
        evidence.write_json(root / 'http-p95-trend.json', evidence.query_range(
            '{__name__=~"k6_ticketing_capacity_.*_duration_ms_p95",testid="' + name + '"}',
            manifest['startEpoch'], time.time()))
        verifier = run_k6.run_command([sys.executable, str(run_k6.VERIFIER)], check=False)
        (root / 'verifier.txt').write_text(verifier.stdout + verifier.stderr, encoding='utf-8')
        manifest['verifierExit'] = verifier.returncode
        metrics = run_k6.read_json(root / 'k6-summary.json')['metrics']
        manifest['business'] = run_k6.read_json(root / 'business-summary.json')
        manifest['failures'] = failures(manifest, metrics)
        manifest['result'] = 'failed gates; do not escalate' if manifest['failures'] else 'hard gates passed; review time trends before escalating'
        print(f'{manifest["result"]}; evidence={root}', flush=True)
        return int(bool(manifest['failures']))
    except Exception as error:
        manifest['error'] = str(error)
        if process is not None and process.poll() is None:
            manifest['generatorStopExit'] = run_k6.run_command(['docker', 'stop', container], check=False).returncode
        print(f'[STOP] {error}; evidence={root}', flush=True)
        return 1
    finally:
        manifest['endEpoch'] = time.time()
        evidence.write_json(root / 'run-manifest.json', manifest)


if __name__ == '__main__':
    raise SystemExit(main())
