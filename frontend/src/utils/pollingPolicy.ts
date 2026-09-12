export const MIN_POLL_MS = 500
export const MAX_POLL_MS = 30000
export function validPollHint(value: unknown, allowZero = false): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isSafeInteger(value) && value >= (allowZero ? 0 : MIN_POLL_MS) && value <= MAX_POLL_MS
}
export function retryHint(body: unknown, header: unknown, now = Date.now()): number | undefined {
  let delay = validPollHint(body, true) ? body : undefined
  if (typeof header === 'string') {
    const value = header.trim()
    const milliseconds = /^\d+$/.test(value) ? Number(value) * 1000 : Date.parse(value) - now
    if (Number.isFinite(milliseconds) && milliseconds >= 0) delay = Math.max(delay ?? 0, Math.min(MAX_POLL_MS, milliseconds))
  }
  return delay
}
export function nextPollDelay(input: {pollAfterMs?: number; emptyStreak: number; errorStreak: number; hasMore?: boolean; retryAfterMs?: number}, rng = Math.random): number {
  if (input.hasMore) return 0
  const hint = validPollHint(input.pollAfterMs) ? input.pollAfterMs : 2000
  const retry = validPollHint(input.retryAfterMs, true) ? input.retryAfterMs : 0
  const streak = Math.max(0, Math.min(5, input.errorStreak || input.emptyStreak - 1))
  const nominal = Math.min(MAX_POLL_MS, hint * 2 ** streak)
  const random = rng(); const jitter = Number.isFinite(random) ? Math.max(0,Math.min(1,random)) : .5
  // Jitter never schedules before a valid server minimum; all input is bounded.
  return Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, hint, retry, Math.round(nominal * (.8 + .4 * jitter))))
}
