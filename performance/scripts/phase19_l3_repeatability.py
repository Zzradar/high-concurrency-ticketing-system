"""Fail-closed independent Open L3 evidence gate; does not generate traffic."""
import math

ORDER = ['precheck', 'l1', 'l2', 'l3']

def qualify(rounds):
    errors = []
    if len(rounds) != 3:
        errors.append('exactly three predeclared independent rounds required')
    identities = set()
    baselines = set()
    for number, round_ in enumerate(rounds, 1):
        prefix = round_.get('prefix')
        if not prefix or prefix in identities:
            errors.append(f'round {number}: reused or missing environment')
        identities.add(prefix)
        baseline = round_.get('initialStateSha256')
        if not baseline or not round_.get('initialVerifierPassed'):
            errors.append(f'round {number}: initial state not verified')
        baselines.add(baseline)
        points = round_.get('points', [])
        if [p.get('name') for p in points] != ORDER:
            errors.append(f'round {number}: frozen order changed or retry inserted')
        for point in points:
            if not point.get('valid'):
                errors.append(f'round {number}: {point.get("name")} failed frozen gate')
        if not points or points[-1].get('name') != 'l3':
            continue
        last = points[-1]
        for key in ['dropped', 'interrupted', 'unexpectedErrors', 'http503']:
            if last.get(key) != 0:
                errors.append(f'round {number}: {key} must be zero')
        if any(not isinstance(last.get(key), (int, float)) or not math.isfinite(last[key]) or last[key] < minimum
               for key, minimum in [('deltaPerSecond', 500), ('writePerSecond', 42.85)]):
            errors.append(f'round {number}: L3 frozen rates not attained')
        if not last.get('inventoryPassed'):
            errors.append(f'round {number}: SQL/Redis inventory failed')
    if len(baselines) != 1:
        errors.append('independent initial states differ')
    return {'qualified': not errors, 'errors': errors}