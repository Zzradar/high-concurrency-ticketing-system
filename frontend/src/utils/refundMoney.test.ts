import { describe, expect, it } from 'vitest'
import { formatMoney } from './money'

describe('Refund immutable currency formatting', () => {
  it('preserves existing CNY presentation', () => {
    expect(formatMoney(12800, 'cny')).toBe('¥128')
    expect(formatMoney(12801, 'CNY')).toBe('¥128.01')
  })
  it('uses the returned currency and its minor-unit exponent', () => {
    expect(formatMoney(12800, 'usd')).toBe('US$128.00')
    expect(formatMoney(12800, 'jpy')).toBe('JP¥12,800')
    expect(formatMoney(12800, 'kwd')).toContain('12.800')
  })
})
