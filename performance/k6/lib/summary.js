function value(data, metric, field, fallback = 0) {
    return data.metrics[metric]?.values?.[field] ?? fallback;
}

function count(data, metric) {
    return value(data, metric, 'count', 0);
}

export function summaryHandler(metadata) {
    return function handleSummary(data) {
        const summary = {
            runId: metadata.runId,
            workload: metadata.workload,
            mode: metadata.mode,
            iterations: count(data, 'iterations'),
            http_reqs: count(data, 'http_reqs'),
            dropped_iterations: count(data, 'dropped_iterations'),
            p50: value(data, 'http_req_duration', 'p(50)'),
            p95: value(data, 'http_req_duration', 'p(95)'),
            p99: value(data, 'http_req_duration', 'p(99)'),
            business_success: count(data, 'ticketing_business_success_total'),
            business_conflict: count(data, 'ticketing_business_conflict_total'),
            capacity_rejection: count(data, 'ticketing_capacity_rejection_total'),
            system_error: count(data, 'ticketing_system_error_total'),
            unexpected: count(data, 'ticketing_unexpected_total'),
        };
        if (metadata.workload === 'formal-seat-contention' || metadata.workload === 'temporary-hold-contention') {
            summary.groups = count(data, 'ticketing_contention_groups_total');
            summary.reservation_attempts = count(data, 'ticketing_reservation_attempts_total');
            summary.invalid_groups = count(data, 'ticketing_contention_group_invalid_total');
            summary.workload_groups = count(data, 'ticketing_workload_groups_total');
            summary.invalid_workload_groups = count(data, 'ticketing_workload_group_invalid_total');
            summary.group_rate = Number(__ENV.GROUP_RATE || 0);
            summary.contenders_per_seat = Number(__ENV.CONTENDERS_PER_SEAT || 0);
        }
        const prefix = `/results/${metadata.runId}`;
        const text = [
            `run=${metadata.runId} workload=${metadata.workload} mode=${metadata.mode}`,
            `iterations=${summary.iterations} http_reqs=${summary.http_reqs} dropped=${summary.dropped_iterations}`,
            `success=${summary.business_success} conflict=${summary.business_conflict} capacity=${summary.capacity_rejection}`,
            `system_error=${summary.system_error} unexpected=${summary.unexpected}`,
            `latency_ms p50=${summary.p50} p95=${summary.p95} p99=${summary.p99}`,
        ].join('\n') + '\n';
        return {
            stdout: text,
            [`${prefix}/k6-summary.json`]: JSON.stringify(data, null, 2),
            [`${prefix}/business-summary.json`]: JSON.stringify(summary, null, 2),
        };
    };
}
