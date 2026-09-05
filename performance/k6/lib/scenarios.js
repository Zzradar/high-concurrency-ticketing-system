import { positiveInteger } from './config.js';

export function scenarioFor(mode, rateVariable = 'RATE', gracefulStop = '30s') {
    if (mode === 'smoke') {
        return {
            smoke: {
                executor: 'shared-iterations',
                vus: 1,
                iterations: 3,
                maxDuration: '30s',
                gracefulStop,
            },
        };
    }
    const preAllocatedVUs = positiveInteger('PREALLOCATED_VUS');
    if (mode === 'steady' || mode === 'soak') {
        return {
            steady: {
                executor: 'constant-arrival-rate',
                rate: positiveInteger(rateVariable),
                timeUnit: '1s',
                duration: __ENV.DURATION || '10s',
                preAllocatedVUs,
                gracefulStop,
            },
        };
    }
    if (mode === 'spike') {
        return {
            spike: {
                executor: 'ramping-arrival-rate',
                startRate: positiveInteger('START_RATE'),
                timeUnit: '1s',
                preAllocatedVUs,
                gracefulStop,
                stages: [
                    {target: positiveInteger('START_RATE'), duration: __ENV.BASE_DURATION || '5s'},
                    {target: positiveInteger('TARGET_RATE'), duration: __ENV.RAMP_DURATION || '5s'},
                    {target: positiveInteger('TARGET_RATE'), duration: __ENV.HOLD_DURATION || '5s'},
                    {target: positiveInteger('START_RATE'), duration: __ENV.RECOVERY_DURATION || '5s'},
                    {target: 0, duration: __ENV.RAMP_DOWN_DURATION || '5s'},
                ],
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
            gracefulStop,
            stages,
        },
    };
}

export function correctnessThresholds(mode, grouped = false) {
    if (mode === 'discovery') {
        return {};
    }
    const thresholds = {
        ticketing_system_error_total: ['count==0'],
        ticketing_unexpected_total: ['count==0'],
        ticketing_expected_result_rate: ['rate==1'],
        dropped_iterations: ['count==0'],
    };
    if (grouped) {
        thresholds.ticketing_workload_group_invalid_total = ['count==0'];
    }
    return thresholds;
}
