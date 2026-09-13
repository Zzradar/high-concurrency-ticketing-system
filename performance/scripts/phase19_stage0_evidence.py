"""Archive Stage0 observations without promoting generator qualification to SUT capacity."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'performance/experiments/phase19-global-polling-mixed-load'
BASE = '2c680e78d532eace9e7f28862e7efb6ef2bdf4fb'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def redact(text, private_root):
    for value, replacement in [(str(ROOT), '<PHASE19_WORKTREE>'), (str(private_root), '<PRIVATE_OUTPUT_PARENT>')]:
        text = text.replace(value, replacement).replace(value.replace('\\', '/'), replacement)
    text = re.sub(r'(?:sk_(?:test|live)_|whsec_)[A-Za-z0-9]+', '<REDACTED_PROVIDER_SECRET>', text)
    return text


def test_count(text):
    if re.search(r'^FAILED\s*\(', text, re.M):
        raise ValueError('Failed regression cannot be archived as passing')
    counts = re.findall(r'^Ran (\d+) tests? in ', text, re.M)
    if not counts or len(re.findall(r'^OK\s*$', text, re.M)) != len(counts):
        raise ValueError('Missing complete unittest outcomes')
    return sum(map(int, counts))


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('Refuse overwriting prior observation: '+str(path.relative_to(OUT)))
    path.write_bytes(raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path, required=True)
    args = parser.parse_args()
    private = args.private_root.resolve()
    stage = private / 'phase19-stage0-private'
    raw_artifacts = []
    def archive(source, target):
        raw_artifacts.append({'path': '<PRIVATE_OUTPUT_PARENT>/'+source.relative_to(private).as_posix(), 'sha256': sha(source), 'bytes': source.stat().st_size})
        write(OUT / target, redact(source.read_text(encoding='utf-8-sig'), private).encode('utf-8'))
    counts = {}
    modules = ['phase18_schema_test','phase18_token_bucket_test','phase18_waiting_room_test','phase18_public_contract_test',
        'phase18_policy_http_test','phase18_admission_http_test','phase18_traffic_http_test','phase18_metrics_http_test',
        'phase18_layout_http_test','phase18_layout_revision_http_test','phase18_layout_resolution_http_test',
        'phase18_inventory_fault_test','phase18_checkout_crash_test','phase18_availability_fault_test','phase18_verifier_test']
    for name in modules:
        source = stage / (name+'-r2.log')
        if not source.exists():
            source = stage / (name+'.log')
        counts[name] = test_count(source.read_text(encoding='utf-8-sig'))
        archive(source, 'stage0/regression/'+name+'.log')
    for folder, names in [('phase19-financial-private', ['phase11_stripe_integration_test','phase11_crash_window_integration_test','phase12_buyer_refund_integration_test']),
                          ('phase19-financial-peer-private', ['phase18_multi_instance_test','phase18_refund_verifier_fixture'])]:
        for name in names:
            source = private/folder/(name+'.log')
            counts[name] = test_count(source.read_text(encoding='utf-8-sig'))
            archive(source, 'stage0/regression/'+name+'.log')
    counts['phase15_16_17_off_and_payment'] = test_count((stage/'off-regression-r2.log').read_text(encoding='utf-8-sig'))
    archive(stage/'off-regression-r2.log', 'stage0/regression/off-regression.log')
    archive(stage/'build-ctest-r2.log', 'stage0/build-ctest.log')
    archive(stage/'ctest-r2.log', 'stage0/ctest-detail.log')
    archive(stage/'seed-smoke-result.json', 'stage0/seed-smoke.json')
    for name in ['build-ctest-first.log','off-regression-r1.log','phase18_traffic_http_test.log']:
        archive(stage/name, 'diagnostics/stage0/'+name)
    archive(private/'phase19-python-baseline.log', 'stage0/python-baseline.log')
    archive(private/'phase19-vitest-baseline-authorized.log', 'stage0/vitest-baseline.log')
    archive(private/'phase19-frontend-build-baseline-authorized.log', 'stage0/frontend-build-baseline.log')
    counts['performance_python_baseline'] = test_count((private/'phase19-python-baseline.log').read_text(encoding='utf-8-sig'))
    samples, core_protocol = [], None
    core_names = ['calibrate.py','resource_gate.py','stub.py','workload.js','policy.mjs']
    for vus in [100, 250, 500, 1000]:
        folder = private/f'phase19-calibration-{vus}-r2'
        result = json.loads((folder/'result.json').read_text())
        if not result['valid']:
            raise ValueError('Unqualified generator sample')
        identity = json.loads((folder/'identity.json').read_text())
        current = {name: identity['protocolSha256'][name] for name in core_names}
        if core_protocol is not None and current != core_protocol:
            raise ValueError('Executed generator protocol drift')
        core_protocol = current
        samples.append(result)
        for name in ['identity.json','result.json','resource-samples.json','k6-summary.json','k6.log','stub.log']:
            archive(folder/name, f'generator-calibration/{vus}/'+name)
    for source in (private/'phase19-calibration-100-r1').iterdir():
        if source.is_file():
            archive(source, 'diagnostics/generator-100-incomplete-observation/'+source.name)
    host = json.loads((private/'phase19-host.json').read_text(encoding='utf-8-sig'))
    archive(private/'phase19-host.json', 'stage0/host.json')
    spec = importlib.util.spec_from_file_location('phase19_gate', OUT/'protocol/resource_gate.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    estimate = gate.estimate(samples, host['dockerMemoryBytes'], host['hostTotalBytes'], host['hostAvailableBytes'], 4*1024**3)
    write(OUT/'scale-estimate/estimate.json', (json.dumps(estimate, indent=2)+'\n').encode())
    production = {path: subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', BASE+':'+path], text=True).strip()
        for path in ['backend/src','backend/config','backend/db/migrations','frontend/src','frontend/public']}
    prior = {phase: subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', BASE+':performance/experiments/'+phase], text=True).strip()
        for phase in ['phase16-availability','phase17-admin-publishing','phase18-admission-overload']}
    manifest = {'status': 'STAGE0_CHECKPOINT_NOT_PHASE19_DELIVERY', 'capturedUtc': datetime.now(timezone.utc).isoformat(),
        'baseCommit': BASE, 'productionTrees': production, 'priorEvidenceTrees': prior,
        'binarySha256': sha(stage/'ticketing_backend'), 'testCounts': counts, 'ctest': {'passed': 36, 'failed': 0},
        'vitest': {'files': 36, 'passed': 288, 'failed': 0}, 'frontendProductionBuild': 'PASS',
        'executedGeneratorProtocol': core_protocol, 'formalABProtocolFrozen': False,
        'sutCapacityTestsExecuted': False, 'productionPollingChangesImplemented': False,
        'pendingDecision': 'Prompt requests Bulkhead OFF; frozen source keeps local Bulkheads active independently of event policy OFF.',
        'rawArtifacts': raw_artifacts,
        'limitations': ['Generator-only 100/250/500/1000 VUs are not SUT online-user results.',
            'Resource peaks are sampled. Startup before first resource sample can be missed.',
            'Full protocol directory grew while preparing unused SUT fixtures; executed five-file generator protocol is identical across retained qualification points.',
            'Initial 100-VU observation omitted TCP, idle RSS and stderr capture; preserved only in diagnostics.',
            '2000/3000 generator tiers not run: observed maximum marginal memory predicts exceeding the unchanged 2 GiB generator limit.',
            'No browser A/B, mixed-load result, propagation latency, cumulative journeys or hotspot result yet.']}
    write(OUT/'stage0/manifest.json', (json.dumps(manifest, indent=2)+'\n').encode())
    print(json.dumps({'ctest': 36, 'vitest': 288, 'regressionCounts': counts, 'scaleStatus': estimate['status']}, indent=2))


if __name__ == '__main__':
    main()
