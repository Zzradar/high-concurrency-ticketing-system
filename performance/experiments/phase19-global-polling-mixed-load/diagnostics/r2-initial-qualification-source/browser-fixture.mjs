// Controlled HTTP fixtures for frontend polling only. No financial provider is called.
// Separate real-SUT load and Fake Provider integration suites verify backend semantics.
export function fixture(scene) {
  const state = { authenticated: true, terminal: false, processing: scene === 'submitting' };
  const at = new Date().toISOString(), future = '2030-12-01T00:00:00.000Z';
  const salesWindow = { startsAt: '2026-01-01T00:00:00.000Z', endsAt: future, evaluatedAt: at, state: 'OPEN' };
  const user = { id: 'phase19-browser-user', username: 'phase19-browser', displayName: 'Phase19 Browser', role: 'CUSTOMER' };
  const event = { id: 'phase19-browser-event', name: 'Phase19 polling fixture', description: 'Controlled browser fixture', city: '测试', venue: '测试场馆', dateRange: '2030', cover: '', category: '演唱会', status: 'ON_SALE', sessionCount: 1, salesWindow };
  const session = { id: 'phase19-browser-session', eventId: event.id, date: '12月01日', time: '19:30', weekday: '周日', venue: '测试场馆', gateTime: '17:30', status: 'ON_SALE', priceFrom: 10000, availability: '充足', salesWindow };
  event.admission = session.admission = { required: false, state: 'NOT_REQUIRED', prequeueStartsAt: null };
  const seats = Array.from({ length: 5000 }, (_, i) => ({ id: 'phase19-browser-seat-' + i, label: 'R' + (Math.floor(i / 100) + 1) + '-' + (i % 100 + 1), row: 'R' + String(Math.floor(i / 100) + 1).padStart(3, '0'), number: i % 100 + 1, zone: 'Zone-' + Math.floor(i / 1000), price: 10000 }));
  const order = () => ({ id: 'phase19-browser-order', reservationId: 'phase19-browser-reservation', eventId: event.id, sessionId: session.id, seatIds: [seats[0].id], status: scene === 'refund' ? (state.terminal ? 'CANCELLED' : 'PAID') : (state.terminal ? 'PAID' : 'PENDING_PAYMENT'), totalAmount: 10000, expiresAt: future, createdAt: at,
    buyerRefund: scene === 'refund' && state.processing ? refund() : null, refundEligibility: { eligible: scene === 'refund' && !state.processing, deadline: future, reason: state.processing ? 'ALREADY_REQUESTED' : null } });
  const refund = () => ({ id: 'phase19-browser-refund', orderId: 'phase19-browser-order', status: state.terminal ? 'SUCCEEDED' : 'PROCESSING', amount: 10000, currency: 'CNY', source: 'BUYER', reason: 'BUYER_REQUESTED', paymentAttemptId: 'phase19-browser-attempt', createdAt: at });
  const attempt = () => ({ id: 'phase19-browser-attempt', orderId: 'phase19-browser-order', status: state.terminal ? 'SUCCEEDED' : 'PROCESSING', provider: 'simulation', startedAt: at, processingDeadline: future });
  const checkout = () => ({ id: 'phase19-browser-checkout', userId: user.id, sessionId: session.id, seatIds: [seats[0].id], status: state.terminal ? 'RESERVED' : state.processing ? 'SUBMITTING' : 'SELECTING', revision: 0, createdAt: at, updatedAt: at, ...(state.terminal ? { order: order() } : {}) });
  function response(method, url) {
    const p = url.pathname.replace(/^\/api/, '');
    if (p === '/auth/logout') { state.authenticated = false; return [200, {}]; }
    if (p === '/auth/me') return state.authenticated ? [200, user] : [401, { code: 'UNAUTHENTICATED', message: 'Logged out' }];
    if (p === '/notifications') return state.authenticated ? [200, []] : [401, { code: 'UNAUTHENTICATED', message: 'Logged out' }];
    if (p === '/events') return [200, [event]];
    if (p === '/events/' + event.id) return [200, event];
    if (p === '/events/' + event.id + '/sessions') return [200, [session]];
    if (p === '/sessions/' + session.id) return [200, session];
    if (p.endsWith('/seat-layout')) return [200, { sessionId: session.id, seats }];
    if (p.endsWith('/seats') && method === 'GET') return [200, seats.map(s => ({ ...s, sessionId: session.id, status: 'AVAILABLE' }))];
    if (p.endsWith('/seat-availability')) {
      const zone = url.searchParams.get('zone') || 'Zone-0', delta = url.searchParams.has('since');
      return [200, { sessionId: session.id, zone, mode: delta ? 'delta' : 'snapshot', generation: 'phase19-browser-generation', cursor: '1-0', reset: !delta, degraded: false, hasMore: false, pollAfterMs: delta ? 5000 : 2000,
        zones: Array.from({ length: 5 }, (_, i) => ({ zone: 'Zone-' + i, total: 1000, available: 1000, held: 0, sold: 0 })), ...(delta ? { changes: [] } : { seats: seats.filter(s => s.zone === zone).map(s => ({ id: s.id, status: 'AVAILABLE' })) }) }];
    }
    if (p === '/orders') return [200, []];
    if (p === '/orders/phase19-browser-order') return [200, order()];
    if (p.endsWith('/pay')) { state.processing = true; return [200, { disposition: 'STARTED_NEW', order: order(), paymentAttempt: attempt(), paymentAction: null }]; }
    if (p.startsWith('/payment-attempts/')) return [200, attempt()];
    if (p.endsWith('/refunds')) { state.processing = true; return [202, { refund: refund(), pollAfterMs: 5000 }]; }
    if (p === '/checkout-sessions') return [200, scene === 'submitting' ? [checkout()] : []];
    if (p.endsWith('/confirm')) { state.processing = true; return [200, { disposition: 'REUSED_CONFIRMATION', checkoutSession: checkout() }]; }
    if (p === '/checkout-sessions/phase19-browser-checkout') return [200, checkout()];
    return [404, { code: 'UNEXPECTED_FIXTURE_ROUTE', message: method + ' ' + p }];
  }
  return { state, response, user, session, order, checkout };
}
