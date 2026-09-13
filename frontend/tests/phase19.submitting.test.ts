import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { authState } from '../src/auth/authState'
import { resetMockData, setMockLatency, ticketApi, TicketApiError } from '../src/api/ticketApi'
import { router } from '../src/router'
import type { CheckoutSession } from '../src/types'

let wrapper: ReturnType<typeof mount> | undefined, checkout: CheckoutSession, hidden = false
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
beforeEach(async () => {
  resetMockData(); setMockLatency(0); authState.clearAuth(); sessionStorage.clear()
  await authState.login('demo', 'Ticketing123!')
  await router.push('/sessions/ses-concert-1001/seats'); await router.isReady()
  const layout = await ticketApi.getSeatLayout('ses-concert-1001')
  checkout = { id: 'phase19-checkout', userId: authState.currentUser.value!.id, sessionId: 'ses-concert-1001', seatIds: [layout[0]!.id], status: 'SUBMITTING', revision: 1, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() }
  vi.useFakeTimers(); vi.spyOn(Math, 'random').mockReturnValue(.5); hidden = false
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => hidden ? 'hidden' : 'visible')
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  vi.spyOn(ticketApi, 'listRecoverableCheckoutSessions').mockResolvedValue([checkout])
  vi.spyOn(ticketApi, 'getCheckoutSession').mockImplementation(async () => ({ ...checkout }))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers(); vi.restoreAllMocks() })
async function open() {
  wrapper = mount(App, { global: { plugins: [router] } })
  await vi.advanceTimersByTimeAsync(100)
  const button = wrapper.findAll('button').find(b => b.text() === '继续处理')
  expect(button).toBeDefined(); await button!.trigger('click'); await vi.advanceTimersByTimeAsync(20)
}
async function visibility(value: boolean) {
  hidden = value; document.dispatchEvent(new Event('visibilitychange'))
  if (!value) window.dispatchEvent(new Event('focus'))
  await vi.advanceTimersByTimeAsync(20)
}

describe('Phase19 unknown Checkout recovery', () => {
  it('pauses hidden, performs one final read after its deadline and stops until manual recovery', async () => {
    await open(); await visibility(true)
    const before = vi.mocked(ticketApi.getCheckoutSession).mock.calls.length
    await vi.advanceTimersByTimeAsync(91000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(before)
    await visibility(false)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(before + 1)
    expect(wrapper!.text()).toContain('继续原确认')
    await vi.advanceTimersByTimeAsync(30000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(before + 1)
  })
  it('coalesces an in-flight Checkout read with focus and does not start a second timer', async () => {
    const pending = deferred<CheckoutSession>()
    vi.mocked(ticketApi.getCheckoutSession).mockReturnValueOnce(pending.promise)
    await open(); window.dispatchEvent(new Event('focus')); await flushPromises()
    await vi.advanceTimersByTimeAsync(5000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(1)
    pending.resolve({ ...checkout }); await vi.advanceTimersByTimeAsync(20)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(1)
  })
  it('a short second tab activation still restores one Checkout read', async () => {
    await open(); window.dispatchEvent(new Event('focus')); await vi.advanceTimersByTimeAsync(20)
    const before = vi.mocked(ticketApi.getCheckoutSession).mock.calls.length
    await visibility(true); await vi.advanceTimersByTimeAsync(100); await visibility(false)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(before + 1)
  })
  it('leaving the route invalidates a late RESERVED response', async () => {
    const pending = deferred<CheckoutSession>()
    vi.mocked(ticketApi.getCheckoutSession).mockReturnValueOnce(pending.promise)
    await open(); await router.push('/events'); await vi.advanceTimersByTimeAsync(20)
    pending.resolve({ ...checkout, status: 'RESERVED', order: { id: 'old-order', reservationId: 'old-reservation', eventId: 'evt-concert', sessionId: checkout.sessionId, seatIds: checkout.seatIds, status: 'PENDING_PAYMENT', totalAmount: 100, createdAt: checkout.createdAt, expiresAt: new Date(Date.now() + 60000).toISOString(), buyerRefund: null } })
    await vi.advanceTimersByTimeAsync(20000)
    expect(router.currentRoute.value.path).toBe('/events')
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(1)
  })
  it('identity loss invalidates an in-flight Checkout and does not restore it', async () => {
    const pending = deferred<CheckoutSession>()
    vi.mocked(ticketApi.getCheckoutSession).mockReturnValueOnce(pending.promise)
    await open(); authState.clearAuth(); await vi.advanceTimersByTimeAsync(20)
    pending.resolve({ ...checkout }); await vi.advanceTimersByTimeAsync(20000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).not.toContain('继续原确认')
  })
  it('identity loss also stops the former account seat polling before navigation', async () => {
    await open()
    const availability = vi.spyOn(ticketApi, 'getSeatAvailability')
    authState.clearAuth(); await vi.advanceTimersByTimeAsync(20)
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(91000)
    expect(availability).not.toHaveBeenCalled()
  })
  it.each([429, 503])('respects %s Retry-After but stops at the wall-clock deadline', async status => {
    vi.mocked(ticketApi.getCheckoutSession).mockRejectedValue(new TicketApiError('busy', 'BUSY', status, 120000))
    await open(); await vi.advanceTimersByTimeAsync(15000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).toContain('继续原确认')
    await vi.advanceTimersByTimeAsync(120000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(1)
  })
  it('a non-SUBMITTING authority stops automatic Checkout reads', async () => {
    await open(); checkout.status = 'SELECTING'
    await vi.advanceTimersByTimeAsync(2100)
    const before = vi.mocked(ticketApi.getCheckoutSession).mock.calls.length
    await vi.advanceTimersByTimeAsync(30000)
    expect(ticketApi.getCheckoutSession).toHaveBeenCalledTimes(before)
  })
})
