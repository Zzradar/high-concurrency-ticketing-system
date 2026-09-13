import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Ref } from 'vue'
import OrderPage from '../src/pages/OrderPage.vue'
import { authState } from '../src/auth/authState'
import { ticketApi, TicketApiError } from '../src/api/ticketApi'
import { orderFixture, refundFixture, summaryFixture } from '../src/test/refundFixtures'
import type { CurrentUser, PaymentAttempt, TicketOrder } from '../src/types'

vi.mock('../src/auth/authState', async () => {
  const { ref } = await import('vue')
  return { authState: { currentUser: ref(null) } }
})
const user = authState.currentUser as Ref<CurrentUser | null>
let current: TicketOrder, attempt: PaymentAttempt, hidden = false
let wrapper: VueWrapper | undefined
let router: ReturnType<typeof createRouter>
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
async function open() {
  router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/orders/:orderId', component: OrderPage },
    { path: '/orders', name: 'orders', component: { template: '<p>Orders</p>' } },
    { path: '/events', name: 'events', component: { template: '<p>Events</p>' } },
  ] })
  await router.push('/orders/' + current.id)
  wrapper = mount(OrderPage, { global: { plugins: [router] } })
  await flushPromises()
}
async function click(text: string) {
  const button = wrapper!.findAll('button').find(b => b.text() === text)
  if (!button) throw new Error('Missing button: ' + text)
  await button.trigger('click'); await flushPromises()
}
async function pay() { await wrapper!.get('.order-pay-button').trigger('click'); await flushPromises() }
async function visibility(value: boolean) {
  hidden = value; document.dispatchEvent(new Event('visibilitychange'))
  if (!value) window.dispatchEvent(new Event('focus'))
  await flushPromises()
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-09T02:00:00Z'))
  vi.spyOn(Math, 'random').mockReturnValue(.5)
  hidden = false; user.value = { id: 'buyer-A', username: 'buyer-A', displayName: 'Buyer A', role: 'CUSTOMER' }
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => hidden ? 'hidden' : 'visible')
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  current = { ...structuredClone(orderFixture), status: 'PENDING_PAYMENT', buyerRefund: null }
  attempt = { id: 'P1', orderId: current.id, provider: 'simulation', status: 'PROCESSING', startedAt: new Date().toISOString(), processingDeadline: new Date(Date.now() + 60000).toISOString() }
  vi.spyOn(ticketApi, 'getOrder').mockImplementation(async () => structuredClone(current))
  vi.spyOn(ticketApi, 'getPaymentAttempt').mockImplementation(async () => ({ ...attempt }))
  vi.spyOn(ticketApi, 'payOrder').mockImplementation(async () => ({ disposition: 'STARTED_NEW', order: structuredClone(current), paymentAttempt: { ...attempt }, paymentAction: null }))
  vi.spyOn(ticketApi, 'getEvent').mockResolvedValue({ id: current.eventId, name: 'Polling test', description: '', city: '', venue: '', dateRange: '', salesWindow: { startsAt: '2026-01-01T00:00:00Z', endsAt: '2026-12-01T00:00:00Z', evaluatedAt: '2026-09-01T00:00:00Z', state: 'OPEN' }, status: 'ON_SALE', cover: '', sessionCount: 1, category: '' })
  vi.spyOn(ticketApi, 'getSession').mockResolvedValue({ id: current.sessionId, eventId: current.eventId, date: '', time: '', weekday: '', venue: '', gateTime: '', salesWindow: { startsAt: '2026-01-01T00:00:00Z', endsAt: '2026-12-01T00:00:00Z', evaluatedAt: '2026-09-01T00:00:00Z', state: 'OPEN' }, status: 'ON_SALE', priceFrom: 100, availability: '充足' })
  vi.spyOn(ticketApi, 'getSeats').mockResolvedValue([])
  vi.spyOn(ticketApi, 'createRefund').mockImplementation(async () => {
    current.buyerRefund = { ...summaryFixture }
    return { disposition: 'CREATED', refund: { ...refundFixture }, pollAfterMs: 5000 }
  })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.useRealTimers() })

describe('Phase19 payment and refund polling contract', () => {
  it('keeps the local countdown ticking without periodic HTTP', async () => {
    current.expiresAt = new Date(Date.now() + 60000).toISOString()
    await open(); expect(wrapper!.get('.countdown strong').text()).toBe('01:00')
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper!.get('.countdown strong').text()).toBe('00:59')
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(1)
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
  })
  it('hidden payment crosses its wall deadline, resumes once, then requires manual recovery', async () => {
    await open(); await pay(); await visibility(true)
    const before = vi.mocked(ticketApi.getPaymentAttempt).mock.calls.length
    await vi.advanceTimersByTimeAsync(91000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(before)
    await visibility(false)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(before + 1)
    expect(wrapper!.text()).toContain('支付结果仍在处理中')
    await vi.advanceTimersByTimeAsync(10000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(before + 1)
    current.status = 'PAID'; attempt.status = 'SUCCEEDED'
    await click('刷新状态')
    const settled = vi.mocked(ticketApi.getPaymentAttempt).mock.calls.length
    await vi.advanceTimersByTimeAsync(30000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(settled)
    expect(wrapper!.text()).toContain('支付成功')
  })
  it('timer, focus and manual payment recovery share the same in-flight attempt read', async () => {
    await open()
    const pending = deferred<PaymentAttempt>()
    vi.mocked(ticketApi.getPaymentAttempt).mockReturnValueOnce(pending.promise)
    await pay(); window.dispatchEvent(new Event('focus')); await flushPromises()
    await click('刷新状态'); await vi.advanceTimersByTimeAsync(5000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(1)
    pending.resolve({ ...attempt }); await flushPromises()
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(1)
  })
  it('serializes visible final payment authority behind an obsolete hidden-period read', async () => {
    await open()
    const pending = deferred<PaymentAttempt>()
    vi.mocked(ticketApi.getPaymentAttempt).mockReturnValueOnce(pending.promise)
    await pay(); await visibility(true); await vi.advanceTimersByTimeAsync(91000)
    await visibility(false); expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(1)
    pending.resolve({ ...attempt }); await flushPromises()
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(30000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(2)
  })
  it('payment Retry-After cannot extend its automatic recovery deadline', async () => {
    await open()
    vi.mocked(ticketApi.getPaymentAttempt).mockRejectedValue(new TicketApiError('busy', 'BUSY', 503, 120000))
    await pay(); await vi.advanceTimersByTimeAsync(15000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).toContain('支付结果仍在处理中')
    await vi.advanceTimersByTimeAsync(120000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(1)
  })
  it('uses refund pollAfterMs and backs off errors without changing business state', async () => {
    current = structuredClone(orderFixture); await open()
    await click('申请全额退款'); await click('确认退款')
    const before = vi.mocked(ticketApi.getOrder).mock.calls.length
    await vi.advanceTimersByTimeAsync(4999); expect(ticketApi.getOrder).toHaveBeenCalledTimes(before)
    vi.mocked(ticketApi.getOrder).mockRejectedValueOnce(new TicketApiError('busy', 'BUSY', 429, 12000))
    await vi.advanceTimersByTimeAsync(1); expect(ticketApi.getOrder).toHaveBeenCalledTimes(before + 1)
    expect(wrapper!.text()).toContain('退款处理中')
    await vi.advanceTimersByTimeAsync(11999); expect(ticketApi.getOrder).toHaveBeenCalledTimes(before + 1)
    await vi.advanceTimersByTimeAsync(1); expect(ticketApi.getOrder).toHaveBeenCalledTimes(before + 2)
  })
  it('logout invalidates a late Order and stops its processing recovery', async () => {
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await open(); user.value = null; await flushPromises()
    pending.resolve({ ...current, buyerRefund: { ...summaryFixture } }); await flushPromises()
    expect(wrapper!.text()).not.toContain('退款处理中')
    await vi.advanceTimersByTimeAsync(60000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(1)
  })
  it('route changes invalidate old reads before restoring the next order', async () => {
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await open(); const old = structuredClone(current)
    current = { ...current, id: 'NEXT', status: 'PAID' }
    await router.push('/orders/NEXT'); await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(1)
    pending.resolve(old); await flushPromises()
    expect(wrapper!.text()).toContain('支付成功')
    expect(wrapper!.text()).not.toContain('待支付')
  })
})
