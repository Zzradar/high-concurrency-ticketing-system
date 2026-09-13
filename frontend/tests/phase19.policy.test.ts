import { describe, expect, it } from 'vitest'
import { nextPollDelay, retryHint } from '../src/utils/pollingPolicy'

describe('Phase19 server retry minimum', () => {
  it('preserves a Retry-After larger than the ordinary polling cap', () => {
    expect(retryHint(undefined, '120', 0)).toBe(120000)
    expect(retryHint(90000, '60', 0)).toBe(90000)
    expect(retryHint(undefined, 'Thu, 01 Jan 1970 00:02:00 GMT', 1000)).toBe(119000)
    for (const rng of [() => 0, () => .5, () => 1]) {
      expect(nextPollDelay({ pollAfterMs: 2000, emptyStreak: 0, errorStreak: 1, retryAfterMs: 120000 }, rng)).toBe(120000)
    }
  })
  it('rejects unsafe timer values instead of overflowing or scheduling before them', () => {
    for (const body of [NaN, Infinity, -1, 1.5, '2000', 2147483648]) expect(retryHint(body, undefined, 0)).toBeUndefined()
    expect(retryHint(undefined, '999999999999999999999', 0)).toBeUndefined()
    expect(retryHint(undefined, 'Wed, 31 Dec 1969 23:59:59 GMT', 0)).toBeUndefined()
  })
})
