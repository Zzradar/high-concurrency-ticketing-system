"""Render existing frozen aggregates; no load generation or outcome reclassification."""
from collections import Counter
import gzip
import json
from pathlib import Path
import sys
EVIDENCE = next(p for p in Path(__file__).resolve().parents if (p/'inventory.json').is_file())

from measure import distribution


def read(path):
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    compressed = Path(str(path) + '.gz')
    return json.loads(gzip.decompress(compressed.read_bytes()))


def count(aggregate, metric, **match):
    total = 0
    for key, value in aggregate['counts'].items():
        name, raw = key.split('|', 1)
        tags = json.loads(raw)
        if name == metric and all(tags.get(k) == v for k, v in match.items()): total += value
    return total


def resource_peaks(rows):
    result = {}
    for role, cpus in [('generator',2),('backend',2),('postgres',1),('redis',1)]:
        points = [r[role] for r in rows if role in r]
        if not points: continue
        result[role] = {key: max(p.get(key, 0) for p in points) for key in
            ['memory','rss','rssPeak','fd','tcpTableEntries','threads','pids','swapOutPages']}
        # Frozen collector divides CPU usage by two for all roles. PG/Redis have one CPU.
        cores = max(p['cpuFraction'] for p in points) * 2
        result[role].update(cpuCoresPeak=cores, cpuQuotaFractionPeak=cores/cpus,
                            minWslAvailableBytes=min(p['linuxAvailable'] for p in points),
                            sampledOom=any(p['oom'] for p in points), sampledRestart=any(p['restarted'] for p in points))
    return result


def capacity(point):
    identity, result, aggregate = [read(point / name) for name in ['identity.json','result.json','aggregate.json']]
    seconds = identity['observeSeconds']
    # Endpoint distributions are already calculated by the frozen measure.py.
    latency = {key: value for key, value in aggregate['httpDurationMs'].items() if key.split('|')[1] == 'observe'}
    successful_http = sum(count(aggregate, 'http_reqs', phase='observe', status=status) for status in ['200','201'])
    summary = {'identity': identity, 'result': result, 'observeHttpLatencyMs': latency,
        'observeSuccessfulHttp': successful_http, 'observeSuccessfulHttpPerSecond': successful_http/seconds,
        'observeDeltaRequests': count(aggregate,'http_reqs',phase='observe',name='GET delta'),
        'observeDeltaReqPerSecond': count(aggregate,'http_reqs',phase='observe',name='GET delta')/seconds,
        'observeHttpStatusCounts': {status:count(aggregate,'http_reqs',phase='observe',status=status) for status in ['200','201','409','429','503','0']},
        'observeHttpWriteRequests': count(aggregate,'phase19_write_requests',phase='observe'),
        'observeHttpWriteReqPerSecond': count(aggregate,'phase19_write_requests',phase='observe')/seconds,
        'resourcePeaks': resource_peaks(read(point/'resources.json')),
        'limits': ['HTTP rates use the fixed observe window; inventory counters include drain and cleanup.',
                   'Main-process RSS/FD differs from full cgroup memory; PG workers are included only by cgroup.',
                   'CPU peaks are sampled, not dedicated-host capacity or guaranteed sub-sample peaks.']}
    summary['observeFlowCompletions'] = {kind: count(aggregate,'phase19_completed',phase='observe',kind=kind)
        for kind in result.get('accounting',{}).get('completedByKind',{})}
    propagation = point/'propagation/result.json'
    if propagation.exists():
        p = read(propagation)
        summary['propagation'] = {'passed':p['passed'], 'categories':{
            category:distribution([s['milliseconds'] for s in p['samples'] if s['category']==category and s['matched']])
            for category in ['temporary','formal','convergence']},
            'mismatches':sum(not s['matched'] for s in p['samples']),
            'scope':'Includes observer drain after load; final cancel formal/convergence share one observation.'}
    return summary


def browser(point):
    first = point['phases'][0]['activationEpochMs']
    timed = [r for r in point['requests'] if r['startEpochMs'] >= first]
    reads = [r for r in timed if r['method']=='GET']
    governed = [r for r in reads if r['business']!='other']
    return {'allHttpIncludingSetup':len(point['requests']), 'timedHttp':len(timed),
        'timedGet':len(reads), 'timedGovernedGet':len(governed),
        'timedDecodedBodyBytes':sum(r.get('decodedBodyBytes',0) for r in timed),
        'timedGovernedDecodedBodyBytes':sum(r.get('decodedBodyBytes',0) for r in governed),
        'timedEndpointCounts':dict(Counter(r['method']+' '+r['endpoint'] for r in timed)),
        'timedGovernedByFamily':dict(Counter(r['business'] for r in governed)),
        'checks':point['checks'], 'errors':point['errors'],
        'scope':'Timed counts include explicit scripted actions and lifecycle; setup kept separately. No compressed-wire claim.'}


def main():
    result = {'method':'Existing frozen aggregate counts and measure.distribution; report rendering only', 'capacity':{}, 'browser':{}}
    folder = EVIDENCE/'capacity-thousands/baseline'
    for path in sorted(folder.glob('*/aggregate.json')):
        result['capacity'][path.parent.name] = capacity(path.parent)
    for revision in ['baseline','after']:
        result['browser'][revision] = {}
        for path in sorted((EVIDENCE/('polling-'+revision)).glob('*/browser.json')):
            result['browser'][revision][path.parent.name] = browser(read(path))
    target = EVIDENCE/'report-tables.json'
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
