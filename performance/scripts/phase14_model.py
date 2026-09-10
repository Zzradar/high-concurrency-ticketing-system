"""Frozen Phase14 input model. All indices are zero-based, half-open per run."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

TARGETS = Path(__file__).resolve().parents[1] / 'baseline' / 'phase14-targets.json'


def load_targets(path=TARGETS, *, smoke=False):
    raw = Path(path).read_bytes()
    t = json.loads(raw)
    validate(t)
    t['sourceSha256'] = hashlib.sha256(raw).hexdigest()
    t['mode'] = 'smoke' if smoke else 'formal'
    if smoke:
        s = t['smoke']
        t['behavior']['thinkSeconds'] = s['thinkSeconds']
        t['behavior']['refreshSeconds'] = s['refreshSeconds']
        t['dataset'].update({k: s[k] for k in ('registeredUsers', 'activeAuthSessions', 'loginUsers', 'seatsPerSession')})
        for stages in t['online']['rounds']:
            for stage in stages:
                stage.update(users=s['users'], rampSeconds=s['rampSeconds'], holdSeconds=s['holdSeconds'])
        # One ramp per smoke round, retaining the same closed/open model.
        t['online']['rounds'] = [[x[-1]] for x in t['online']['rounds']]
        t['burst'].update(users=s['users'], windowsSeconds=s['burstWindowsSeconds'])
        t['hotspot'].update(users=s['users'], seats=s['hotspotSeats'], windowSeconds=s['hotspotWindowSeconds'])
        t['login'].update(users=s['loginUsers'], windowsSeconds=s['loginWindowsSeconds'], backgroundWarmSeconds=s['backgroundWarmSeconds'], backgroundRecoverySeconds=s['recoverySeconds'])
        t['recovery']['observeSeconds'] = s['recoverySeconds']
        t['expiry'].update(orders=s['users'], futureSeconds=s['expiryFutureSeconds'], maxObserveSeconds=s['expiryObserveSeconds'], afterDrainSeconds=s['expiryAfterDrainSeconds'])
        t['soak']['seconds'] = s['soakSeconds']
        t['generator']['releaseLeadSeconds'] = s['releaseLeadSeconds']
        t['calibration'].update(authSamples=s['authSamples'], baselineSeconds=s['baselineSeconds'])
        t['slices'] = {name: [i*200, (i+1)*200] for i, name in enumerate(t['slices']) if name != 'login'}
        t['slices']['main'] = [0,s['users']]
        t['slices']['calibration'][1] = t['slices']['calibration'][0] + s['authSamples']
        t['slices']['login'] = [s['activeAuthSessions'], s['activeAuthSessions']+s['loginUsers']]
        t['seatSlices'] = {name: [i*250,(i+1)*250] for i,name in enumerate(t['seatSlices'])}
    validate(t)
    return t


def _intervals(values, limit):
    previous = 0
    for start, end in sorted(values):
        if not isinstance(start,int) or not isinstance(end,int) or start < previous or end <= start or end > limit:
            raise ValueError('invalid, overlapping or exhausted slices')
        previous = end


def validate(t):
    if t['version'] != 1 or sum(t['behavior'][k] for k in ('browse','hold','order')) != 100:
        raise ValueError('invalid version or behavior proportions')
    for key in ('thinkSeconds','refreshSeconds'):
        a,b = t['behavior'][key]
        if not 0 < a <= b: raise ValueError('invalid behavior window')
    d = t['dataset']
    if d['activeAuthSessions'] + d['loginUsers'] > d['registeredUsers']:
        raise ValueError('insufficient registered users')
    _intervals(t['slices'].values(),d['registeredUsers'])
    _intervals((v for k,v in t['slices'].items() if k != 'login'),d['activeAuthSessions'])
    if t['slices']['login'][0] < d['activeAuthSessions']:
        raise ValueError('login pool contains existing sessions')
    _intervals(t['seatSlices'].values(),d['events']*d['sessionsPerEvent']*d['seatsPerSession'])
    h = t['hotspot']
    if h['users'] != h['seats']*h['contendersPerSeat']: raise ValueError('hotspot is not exact')
    for stages in t['online']['rounds']:
        previous = 0
        for stage in stages:
            n = stage['users']
            if n <= previous or stage['rampSeconds'] <= 0 or stage['holdSeconds'] <= 0:
                raise ValueError('invalid online stage')
            if any(n*t['behavior'][k] % 100 for k in ('browse','hold','order')):
                raise ValueError('non-integral behavior allocation')
            if n > t['slices']['main'][1]-t['slices']['main'][0]: raise ValueError('main pool exhausted')
            previous = n
    if any(x <= 0 for x in t['burst']['windowsSeconds']+t['login']['windowsSeconds']):
        raise ValueError('invalid burst window')
    if not 1 <= t['generator']['maxShards'] <= 16: raise ValueError('unbounded shard labels')


def group(index, t):
    # A seed-dependent rotation of each 20-person block gives exactly 12/5/3.
    bucket = (index + t['seed']) % 20 * 5
    return 'browse' if bucket < t['behavior']['browse'] else 'hold' if bucket < t['behavior']['browse']+t['behavior']['hold'] else 'order'


def seat(index, t, *, session_count=None):
    d=t['dataset']; count=session_count or d['events']*d['sessionsPerEvent']
    if index < 0 or index >= count*d['seatsPerSession']: raise ValueError('seat pool exhausted')
    ordinal=index%count; number=index//count+1
    event=ordinal//d['sessionsPerEvent']+1; session=ordinal%d['sessionsPerEvent']+1
    return {'sessionId':f'perf-session-{event:03d}-{session:03d}', 'sessionSeatId':f'perf-ss-{event:03d}-{session:03d}-{number:06d}'}


def hotspot(index, t, *, session_count=1, single=False):
    if not 0 <= index < t['hotspot']['users']: raise ValueError('hotspot user exhausted')
    return seat(0 if single else index//t['hotspot']['contendersPerSeat'],t,session_count=session_count)


def segments(count, t):
    if not isinstance(count,int) or not 1 <= count <= t['generator']['maxShards']: raise ValueError('invalid shards')
    points=[str(Fraction(i,count)) for i in range(count+1)]
    return [{'shard':str(i),'segment':f'{points[i]}:{points[i+1]}','sequence':','.join(points)} for i in range(count)]


def online_plan(t, round_index=0):
    """Exact rational integrals, independent of observed response times.

    Refresh during ramps follows the linearly increasing entered population;
    holds use N/mean(refresh). k6 uses integer rates with timeUnit=mean seconds.
    """
    elapsed=0; previous=0; plan=[]
    mean=Fraction(sum(t['behavior']['refreshSeconds']),2)
    for stage in t['online']['rounds'][round_index]:
        n=stage['users']; ramp=stage['rampSeconds']; hold=stage['holdSeconds']
        for kind,duration,a,b in [('ramp',ramp,previous,n),('hold',hold,n,n)]:
            total=Fraction(a+b,2)*duration/mean
            plan.append({'kind':kind,'startSeconds':elapsed,'durationSeconds':duration,
                         'previousUsers':a,'users':b,'enterCount':b-a,
                         'refreshIntegral':str(total),'refreshRateNumeratorStart':a,
                         'refreshRateNumeratorEnd':b,'refreshTimeUnitSeconds':int(mean)})
            elapsed+=duration
        previous=n
    return plan


def background(t, passed_u1, passed_u2):
    target=t['online']['rounds'][0][-1]['users']
    if target in passed_u1 and target in passed_u2: users=target
    elif passed_u2: users=int(max(passed_u2)*t['login']['fallbackFraction'])
    else: raise ValueError('no stable U2 input; login and capacity soak are gated')
    first=t['online']['rounds'][0][0]
    scale=Fraction(users,target)
    return {'users':users,'refresh':str(Fraction(users*2,sum(t['behavior']['refreshSeconds']))),
            'hold':str(Fraction(first['users']*t['behavior']['hold'],first['rampSeconds']*100)*scale),
            'order':str(Fraction(first['users']*t['behavior']['order'],first['rampSeconds']*100)*scale)}
