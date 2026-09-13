export const MIN_POLL_MS = 500
export const MAX_POLL_MS = 30000
export const MAX_TIMER_MS = 2147483647
export function validPollHint(value: unknown, allowZero = false): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isSafeInteger(value) && value >= (allowZero ? 0 : MIN_POLL_MS) && value <= MAX_POLL_MS
}
function validRetry(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= MAX_TIMER_MS
}
export function retryHint(body: unknown, header: unknown, now = Date.now()): number | undefined {
  let delay = validRetry(body) ? body : undefined
  if (typeof header === 'string') {
    const value = header.trim()
    const milliseconds = /^\d+$/.test(value) ? Number(value) * 1000 : Date.parse(value) - now
    if (validRetry(milliseconds)) delay = Math.max(delay ?? 0, milliseconds)
  }
  return delay
}
export function nextPollDelay(
  input: { pollAfterMs?: number; emptyStreak: number; errorStreak: number; hasMore?: boolean; retryAfterMs?: number },
  rng = Math.random,
  bounds: { baseMs: number; maxMs: number } = { baseMs: 2000, maxMs: MAX_POLL_MS },
): number {
  if (input.hasMore) return 0
  const base = Number.isSafeInteger(bounds.baseMs) && bounds.baseMs >= MIN_POLL_MS && bounds.baseMs <= MAX_TIMER_MS ? bounds.baseMs : 2000
  const cap = Number.isSafeInteger(bounds.maxMs) && bounds.maxMs >= base && bounds.maxMs <= MAX_TIMER_MS ? bounds.maxMs : Math.max(base, MAX_POLL_MS)
  const hint = validPollHint(input.pollAfterMs) ? input.pollAfterMs : base
  const retry = validRetry(input.retryAfterMs) ? input.retryAfterMs : 0
  const rawStreak = input.errorStreak || input.emptyStreak - 1
  const streak = Number.isFinite(rawStreak) ? Math.max(0, Math.min(5, rawStreak)) : 0
  const nominal = Math.min(cap, hint * 2 ** streak)
  const random = rng(); const jitter = Number.isFinite(random) ? Math.max(0, Math.min(1, random)) : .5
  // The ordinary backoff is capped; a valid server minimum can exceed that cap.
  return Math.max(MIN_POLL_MS, hint, retry, Math.min(cap, Math.round(nominal * (.8 + .4 * jitter))))
}
