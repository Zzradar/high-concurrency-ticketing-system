import { Counter, Rate } from 'k6/metrics';

export const businessSuccess = new Counter('ticketing_business_success_total');
export const businessConflict = new Counter('ticketing_business_conflict_total');
export const capacityRejection = new Counter('ticketing_capacity_rejection_total');
export const systemError = new Counter('ticketing_system_error_total');
export const unexpected = new Counter('ticketing_unexpected_total');
export const expectedResult = new Rate('ticketing_expected_result_rate');

export const contentionGroups = new Counter('ticketing_contention_groups_total');
export const invalidContentionGroups = new Counter('ticketing_contention_group_invalid_total');
export const reservationAttempts = new Counter('ticketing_reservation_attempts_total');
export const workloadGroups = new Counter('ticketing_workload_groups_total');
export const invalidWorkloadGroups = new Counter('ticketing_workload_group_invalid_total');

const counters = {
    success: businessSuccess,
    business_conflict: businessConflict,
    capacity_rejection: capacityRejection,
    system_error: systemError,
    unexpected,
};

export function recordResult(result, step) {
    const tags = {result, step};
    for (const [name, counter] of Object.entries(counters)) {
        counter.add(name === result ? 1 : 0, tags);
    }
    expectedResult.add(!['system_error', 'unexpected'].includes(result), tags);
}

export function classifyRead(response, expectedStatus, contractIsValid) {
    if (!response || response.status === 0) {
        return 'system_error';
    }
    if (response.status >= 500) {
        return 'system_error';
    }
    if (response.status === expectedStatus) {
        return contractIsValid(response) ? 'success' : 'system_error';
    }
    return 'unexpected';
}
