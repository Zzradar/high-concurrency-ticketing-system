import { positiveInteger } from './config.js';

export function scenarioFor(mode, rateVariable = 'RATE') {
    if (mode === 'smoke') {
        return {
            smoke: {
                executor: 'shared-iterations',
                vus: 1,
                iterations: 3,
                maxDuration: '30s',
            },
        };
    }
    const preAllocatedVUs = positiveInteger('PREALLOCATED_VUS');
    if (mode === 'steady') {
        return {
            steady: {
                executor: 'constant-arrival-rate',
                rate: positiveInteger(rateVariable),
                timeUnit: '1s',
                duration: __ENV.DURATION || '10s',
                preAllocatedVUs,
            },
        };
    }
    const stages = [
        {
            target: positiveInteger('TARGET_RATE'),
            duration: __ENV.RAMP_DURATION || '10s',
        },
    ];
    if (__ENV.HOLD_DURATION) {
        stages.push({target: positiveInteger('TARGET_RATE'), duration: __ENV.HOLD_DURATION});
    }
    return {
        discovery: {
            executor: 'ramping-arrival-rate',
            startRate: positiveInteger('START_RATE'),
            timeUnit: '1s',
            preAllocatedVUs,
            stages,
        },
    };
}

export function correctnessThresholds(mode, formal = false) {
    if (mode === 'discovery') {
        return {};
    }
    const thresholds = {
        ticketing_system_error_total: ['count==0'],
        ticketing_unexpected_total: ['count==0'],
        ticketing_expected_result_rate: ['rate==1'],
        dropped_iterations: ['count==0'],
    };
    if (formal) {
        thresholds.ticketing_contention_group_invalid_total = ['count==0'];
    }
    return thresholds;
}
