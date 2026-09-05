import { SharedArray } from 'k6/data';

export function loadDataset() {
    return JSON.parse(open('/data/dataset.json'));
}

export function loadSessions() {
    return new SharedArray('offline auth sessions', () => JSON.parse(open('/data/sessions.json')));
}

export function loadWorkloadSeats() {
    return new SharedArray('formal workload seats', () => JSON.parse(open('/data/workload-seats.json')));
}

export function loadWorkloadUsers() {
    return new SharedArray('login workload users', () => JSON.parse(open('/data/workload-users.json')));
}

export function loadPaymentOrders() {
    const path = __ENV.PAYMENT_ORDERS_FILE;
    if (!path) throw new Error('PAYMENT_ORDERS_FILE is required');
    return new SharedArray('payment workload orders', () => JSON.parse(open(path)));
}
