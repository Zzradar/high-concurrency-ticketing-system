import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockData, setMockLatency, setMockPaymentSimulation, setMockRefundSimulation, ticketApi } from './ticketApi'

async function settle<T>(promise: Promise<T>): Promise<T> {
  await vi.advanceTimersByTimeAsync(1)
  return promise
}
async function paid() {
  const { order } = await settle(ticketApi.createReservation('ses-concert-1001', ['ses-concert-1001-A01']))
  await settle(ticketApi.payOrder(order.id))
  await vi.advanceTimersByTimeAsync(20)
  return order
}
beforeEach(async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-09T02:00:00Z'))
  resetMockData(); setMockLatency(0)
  setMockPaymentSimulation({ delayMilliseconds: 10, outcome: 'SUCCESS' })
  setMockRefundSimulation({ delayMilliseconds: 4000, outcome: 'SUCCEEDED' })
  await settle(ticketApi.login('demo', 'Ticketing123!'))
})
afterEach(() => { vi.useRealTimers() })

describe('Refund Mock authority and idempotency', () => {
  it.each(['SUCCEEDED', 'FAILED'] as const)('reuses one refund and deterministically finishes %s with correct rights', async (status) => {
    setMockRefundSimulation({ delayMilliseconds: 4000, outcome: status })
    const order = await paid()
    expect((await settle(ticketApi.getOrder(order.id))).refundEligibility).toMatchObject({ eligible: true, reason: null })
    const [first, second] = await settle(Promise.all([ticketApi.createRefund(order.id), ticketApi.createRefund(order.id)]))
    expect(first.disposition).toBe('CREATED')
    expect(first.refund).toMatchObject({ amount: order.totalAmount, currency: 'cny', source: 'BUYER', status: 'PROCESSING' })
    expect(first.refund.failedAt).toBeUndefined()
    expect(second).toMatchObject({ disposition: 'REUSED_PROCESSING', refund: { id: first.refund.id } })
    const processing = await settle(ticketApi.getOrder(order.id))
    expect(processing).toMatchObject({ status: 'PAID', buyerRefund: { status: 'PROCESSING' }, refundEligibility: { eligible: false, reason: 'ALREADY_REQUESTED' } })
    expect(Object.keys(processing.buyerRefund ?? {}).sort()).toEqual(['amount','currency','id','orderId','reason','source','status'])
    expect((await settle(ticketApi.getSeats(order.sessionId))).find((seat) => seat.id === order.seatIds[0])?.status).toBe('SOLD')
    await vi.advanceTimersByTimeAsync(4000)
    const terminal = await settle(ticketApi.getRefund(first.refund.id))
    expect(terminal.status).toBe(status)
    expect(status === 'SUCCEEDED' ? terminal.refundedAt : terminal.failedAt).toMatch(/^2026-09-09T/)
    const latest = await settle(ticketApi.getOrder(order.id))
    expect(latest.status).toBe(status === 'SUCCEEDED' ? 'CANCELLED' : 'PAID')
    expect(latest.paidAt).toBeDefined()
    expect((await settle(ticketApi.getSeats(order.sessionId))).find((seat) => seat.id === order.seatIds[0])?.status).toBe(status === 'SUCCEEDED' ? 'AVAILABLE' : 'SOLD')
    // Re-entry after logout/login still reads server-side mock state.
    await settle(ticketApi.logout()); await settle(ticketApi.login('demo', 'Ticketing123!'))
    expect((await settle(ticketApi.getOrder(order.id))).buyerRefund?.status).toBe(status)
    const list = await settle(ticketApi.getOrders())
    expect(list[0]?.buyerRefund?.id).toBe(first.refund.id)
    expect(list[0]).not.toHaveProperty('refundEligibility')
    expect((await settle(ticketApi.createRefund(order.id))).disposition).toBe('REUSED_TERMINAL')
    expect((await settle(ticketApi.getNotifications())).filter((item) => item.type === (status === 'SUCCEEDED' ? 'REFUND_COMPLETED' : 'REFUND_FAILED'))).toHaveLength(1)
  })

  it('reuses accepted requests after the deadline but rejects new late requests', async () => {
    const order = await paid()
    const first = await settle(ticketApi.createRefund(order.id))
    vi.setSystemTime(new Date('2026-10-02'))
    expect((await settle(ticketApi.createRefund(order.id))).refund.id).toBe(first.refund.id)
    resetMockData(); await settle(ticketApi.login('demo', 'Ticketing123!'))
    setMockPaymentSimulation({ delayMilliseconds: 10, outcome: 'SUCCESS' })
    vi.setSystemTime(new Date('2026-09-09T02:00:00Z'))
    const late = await paid()
    vi.setSystemTime(new Date('2026-10-02'))
    expect((await settle(ticketApi.getOrder(late.id))).refundEligibility?.reason).toBe('REFUND_WINDOW_CLOSED')
    const rejected = expect(ticketApi.createRefund(late.id)).rejects.toMatchObject({ code: 'REFUND_WINDOW_CLOSED' })
    await settle(rejected)
  })

  it('SYSTEM late-payment refunds do not appear as a buyer request', async () => {
    const { order } = await settle(ticketApi.createReservation('ses-concert-1001', ['ses-concert-1001-A01']))
    await settle(ticketApi.payOrder(order.id))
    await settle(ticketApi.cancelOrder(order.id))
    await vi.advanceTimersByTimeAsync(20)
    expect((await settle(ticketApi.getOrder(order.id))).buyerRefund).toBeNull()
    expect((await settle(ticketApi.getOrders()))[0]?.buyerRefund).toBeNull()
    expect((await settle(ticketApi.getNotifications())).some((item) => item.type === 'AUTO_REFUND_COMPLETED')).toBe(true)
  })

  it('rejects unpaid and anonymous requests using existing business errors', async () => {
    const { order } = await settle(ticketApi.createReservation('ses-concert-1001', ['ses-concert-1001-A01']))
    await settle(expect(ticketApi.createRefund(order.id)).rejects.toMatchObject({ code: 'ORDER_NOT_REFUNDABLE' }))
    await settle(ticketApi.logout())
    await settle(expect(ticketApi.getRefund('missing')).rejects.toMatchObject({ code: 'UNAUTHENTICATED' }))
  })
})
