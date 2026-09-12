"""Statistics for complete raw samples; nearest-rank quantiles, no sample selection."""
import math,json
def redis_cli_json(command,raw):
    # redis-cli treats INFO as a raw-text presentation command even with --json.
    return json.dumps(raw) if command.upper()=='INFO' else raw
def summary(samples):
    if not samples:return {'count':0,'errorRate':None,'p50Ms':None,'p95Ms':None,'p99Ms':None}
    values=sorted(s['ms'] for s in samples)
    return {'count':len(samples),'errorRate':sum(s['status']>=400 for s in samples)/len(samples),
            **{f'p{p}Ms':values[math.ceil(len(values)*p/100)-1] for p in (50,95,99)}}
def phase_at(timestamp,hidden_at,restored_at):
    return 'visible' if timestamp<hidden_at else 'hidden' if timestamp<restored_at else 'restored'
