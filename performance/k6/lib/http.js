export function jsonHeaders(extra = {}) {
    return {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...extra,
    };
}

export function authCookie(session) {
    return `ticketing_session=${session.sessionToken}`;
}

export function reservationHeaders(session, idempotencyKey) {
    return jsonHeaders({
        Cookie: `${authCookie(session)}; ticketing_csrf=${session.csrfToken}`,
        Origin: 'http://performance.local',
        'X-CSRF-Token': session.csrfToken,
        'Idempotency-Key': idempotencyKey,
    });
}
