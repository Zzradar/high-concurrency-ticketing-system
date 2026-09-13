// Baseline frontend policy, reproduced here so generator-only and SUT readers are identical.
export function delayMs(hint, empty, errors, rng = Math.random, retry = 0) {
  const valid = v => Number.isSafeInteger(v) && v >= 500 && v <= 30000;
  const base = valid(hint) ? hint : 2000;
  const nominal = Math.min(30000, base * 2 ** Math.max(0, Math.min(5, errors || empty - 1)));
  return Math.min(30000, Math.max(500, base, retry, Math.round(nominal * (.8 + .4 * rng()))));
}

export function compareCursor(a, b) {
  if (!/^\d+-\d+$/.test(a) || !/^\d+-\d+$/.test(b)) throw new Error('Invalid stream cursor');
  const aa = a.split('-').map(BigInt), bb = b.split('-').map(BigInt);
  return aa[0] < bb[0] ? -1 : aa[0] > bb[0] ? 1 : aa[1] < bb[1] ? -1 : aa[1] > bb[1] ? 1 : 0;
}

export function flowKind(index) {
  const n = index % 10;
  return n < 5 ? 'abandon' : n < 7 ? 'adjust' : n < 9 ? 'cancel' : 'expiry';
}

// k6 allocates global VU IDs across scenarios without promising scenario order.
export function writerSlot(globalId, totalVus, capacity) {
  if (!Number.isInteger(globalId) || globalId < 1 || globalId > totalVus || totalVus > capacity) throw new Error('Writer slot outside disjoint pool');
  return globalId - 1;
}

export function validateSync(body, session, zone) {
  if (!body || body.sessionId !== session || body.zone !== zone || body.degraded ||
      !['snapshot', 'delta'].includes(body.mode) || typeof body.generation !== 'string' ||
      typeof body.cursor !== 'string' || typeof body.hasMore !== 'boolean' || typeof body.reset !== 'boolean' ||
      !Number.isSafeInteger(body.pollAfterMs) || body.pollAfterMs < (body.hasMore ? 0 : 500) || body.pollAfterMs > 30000 ||
      !Array.isArray(body.mode === 'snapshot' ? body.seats : body.changes)) throw new Error('Availability contract mismatch');
  compareCursor(body.cursor, body.cursor);
  return body;
}
