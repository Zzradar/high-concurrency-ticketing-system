import { describe, expect, it } from 'vitest'
import { formatFenPrice, parseYuanPrice } from './adminMoney'

describe('exact admin prices', () => {
  it.each([['1', 100], ['1.5', 150], ['1.50', 150], ['0.01', 1],
    ['70368744177664.01', 7036874417766401], ['90071992547409.91', Number.MAX_SAFE_INTEGER]] as const)(
    'converts %s exactly', (input, fen) => expect(parseYuanPrice(input)).toBe(fen))
  it.each(['1.005', '1.999', '0.009', '0', '0.00', '-1', '+1', '1e2', '1E2', '1,000', '', ' ', 'abc', '.5', '1.', '90071992547409.92'])(
    'rejects %s without rounding', value => expect(() => parseYuanPrice(value)).toThrow('票价'))
  it.each([1, 100, 150, 7036874417766401, Number.MAX_SAFE_INTEGER])('round-trips %s fen', fen => {
    expect(parseYuanPrice(formatFenPrice(fen))).toBe(fen)
    expect(formatFenPrice(fen)).toMatch(/^\d+\.\d{2}$/)
  })
  it.each([0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity])('rejects unsafe stored value %s', value => {
    expect(() => formatFenPrice(value)).toThrow()
  })
})
