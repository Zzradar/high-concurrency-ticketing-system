const MODES = new Set(['smoke', 'steady', 'discovery']);

function required(name) {
    const value = __ENV[name];
    if (!value) {
        throw new Error(`${name} is required`);
    }
    return value;
}

export function positiveInteger(name, fallback = null) {
    const raw = __ENV[name] || fallback;
    const value = Number(raw);
    if (!Number.isInteger(value) || value <= 0) {
        throw new Error(`${name} must be a positive integer`);
    }
    return value;
}

export function loadConfig(workload) {
    const mode = __ENV.MODE || 'smoke';
    if (!MODES.has(mode)) {
        throw new Error(`unsupported MODE: ${mode}`);
    }
    return {
        workload,
        mode,
        baseUrl: (__ENV.BASE_URL || 'http://backend:8080').replace(/\/$/, ''),
        runId: required('RUN_ID'),
        shortRunToken: required('SHORT_RUN_TOKEN'),
        duration: __ENV.DURATION || '10s',
    };
}

export const SYSTEM_TAGS = [
    'status',
    'method',
    'name',
    'scenario',
    'expected_response',
    'error_code',
];
