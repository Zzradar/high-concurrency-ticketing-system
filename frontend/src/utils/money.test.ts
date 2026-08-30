import { describe, expect, it } from 'vitest'
import { formatCny } from './money'

describe('formatCny', () => {
  it('formats integer fen as yuan without forced decimal zeros', () => {
    expect(formatCny(128000)).toBe('¥1,280')
    expect(formatCny(58000)).toBe('¥580')
  })

  it('keeps up to two decimal places when fen are present', () => {
    expect(formatCny(128050)).toBe('¥1,280.5')
    expect(formatCny(128001)).toBe('¥1,280.01')
  })
})
