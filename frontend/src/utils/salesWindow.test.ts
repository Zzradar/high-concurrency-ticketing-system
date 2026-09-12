import { expect, it } from 'vitest'
import { salesWindowAt } from './salesWindow'
it('classifies half-open and empty windows without altering configured boundaries', () => {
  const start='2026-09-01T00:00:00Z', end='2026-09-02T00:00:00Z'
  expect(salesWindowAt(start,end,Date.parse(start)-1).state).toBe('NOT_STARTED')
  expect(salesWindowAt(start,end,Date.parse(start)).state).toBe('OPEN')
  expect(salesWindowAt(start,end,Date.parse(end)-1).state).toBe('OPEN')
  expect(salesWindowAt(start,end,Date.parse(end)).state).toBe('ENDED')
  expect(salesWindowAt(start,start,Date.parse(start)-1).state).toBe('ENDED')
  expect(salesWindowAt(start,end,Date.parse(start))).toEqual({startsAt:start,endsAt:end,state:'OPEN',evaluatedAt:'2026-09-01T00:00:00.000Z'})
})
