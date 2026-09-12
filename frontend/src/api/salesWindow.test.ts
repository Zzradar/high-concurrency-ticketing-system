import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { resetMockData, setMockLatency, setMockSalesClock, setMockSalesWindow, ticketApi } from './ticketApi'
const id = 'ses-concert-1001', event = 'evt-concert-2026', seat = id + '-A01'
const start = Date.parse('2026-09-12T00:00:00Z'), end = start + 10000
async function settle<T>(promise: Promise<T>) { await vi.advanceTimersByTimeAsync(5); return promise }
beforeEach(async () => {
  vi.useFakeTimers(); resetMockData(); setMockLatency(0)
  setMockSalesWindow(event, new Date(start).toISOString(), new Date(end).toISOString())
  await settle(ticketApi.login('demo', 'Ticketing123!'))
})
afterEach(() => vi.useRealTimers())
it('uses half-open boundaries on every Mock read and new write', async () => {
  for (const [now, state, code] of [[start-1,'NOT_STARTED','SALES_NOT_STARTED'], [end,'ENDED','SALES_ENDED']] as const) {
    setMockSalesClock(now)
    expect((await settle(ticketApi.getSession(id))).salesWindow.state).toBe(state)
    expect((await settle(ticketApi.getEvent(event))).salesWindow.state).toBe(state)
    await settle(expect(ticketApi.createCheckoutSession(id,[seat])).rejects.toMatchObject({code}))
    await settle(expect(ticketApi.createReservation(id,[seat])).rejects.toMatchObject({code}))
  }
  setMockSalesClock(start)
  expect((await settle(ticketApi.getSession(id))).salesWindow.state).toBe('OPEN')
  const checkout = await settle(ticketApi.createCheckoutSession(id,[seat]))
  setMockSalesClock(end)
  await settle(expect(ticketApi.replaceCheckoutSessionSeats(checkout.id,[seat],0)).rejects.toMatchObject({code:'SALES_ENDED'}))
  expect((await settle(ticketApi.getCheckoutSession(checkout.id))).revision).toBe(0)
  expect((await settle(ticketApi.replaceCheckoutSessionSeats(checkout.id,[],0))).seatIds).toEqual([])
})
it('abandons SELECTING at cutoff and preserves RESERVED replay', async () => {
  setMockSalesClock(start)
  const selecting = await settle(ticketApi.createCheckoutSession(id,[seat]))
  setMockSalesClock(end)
  await settle(expect(ticketApi.confirmCheckoutSession(selecting.id)).rejects.toMatchObject({code:'SALES_ENDED'}))
  expect((await settle(ticketApi.getCheckoutSession(selecting.id))).status).toBe('ABANDONED')
  setMockSalesClock(end-1)
  const open = await settle(ticketApi.createCheckoutSession(id,[seat]))
  const original = await settle(ticketApi.confirmCheckoutSession(open.id))
  setMockSalesClock(end)
  const replay = await settle(ticketApi.confirmCheckoutSession(open.id))
  expect(replay.disposition).toBe('ALREADY_CONFIRMED')
  expect(replay.checkoutSession.order?.id).toBe(original.checkoutSession.order?.id)
})
