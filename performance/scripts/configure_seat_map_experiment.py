#!/usr/bin/env python3
"""Only switch the isolated Performance backend between 2/4 Seat Map workers."""
import argparse
import copy
import json

from run_login_experiment import changed_paths
import run_k6

CONFIG = run_k6.REPO_ROOT / 'backend/config/config.performance.json'
OVERRIDE = run_k6.REPO_ROOT / 'performance/seat-map-experiment-compose.yml'


def build_config(workers):
    if workers not in (2, 4):
        raise ValueError('experiment supports only 2 or 4 workers')
    original = json.loads(CONFIG.read_text(encoding='utf-8'))
    result = copy.deepcopy(original)
    if original['custom_config']['seat_map_compute_queue_capacity'] != 16:
        raise ValueError('experiment queue must remain fixed at 16')
    result['custom_config']['seat_map_compute_workers'] = workers
    if changed_paths(original, result) - {('custom_config', 'seat_map_compute_workers')}:
        raise ValueError('forbidden experiment configuration change')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', required=True, type=int, choices=(2, 4))
    args = parser.parse_args()
    run_k6.write_json(run_k6.GENERATED_ROOT / 'seat-map-experiment-config.json', build_config(args.workers))
    result = run_k6.run_command(run_k6.compose_command(
        '-f', str(OVERRIDE), 'up', '-d', '--no-deps', '--force-recreate', '--wait', 'backend'))
    run_k6.print_console(result.stdout + result.stderr)


if __name__ == '__main__':
    main()
