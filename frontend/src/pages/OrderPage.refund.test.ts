import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import OrderPage from './OrderPage.vue'
import BuyerRefundPanel from '../components/BuyerRefundPanel.vue'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import { orderFixture, refundFixture, summaryFixture } from '../test/refundFixtures'
import type { CreateRefundResult, TicketOrder } from '../types'

let current: TicketOrder
let wrapper: VueWrapper | undefined
let router: ReturnType<typeof createRouter>
function deferred<T>() {
  let resolve: (value: T) => void = () => { throw new Error('not initialized') }
  let reject: (cause: unknown) => void = () => { throw new Error('not initialized') }
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-09T02:00:00Z'))
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  current = structuredClone(orderFixture)
  vi.spyOn(ticketApi, 'getOrder').mockImplementation(async () => structuredClone(current))
  vi.spyOn(ticketApi, 'getEvent').mockResolvedValue({ id: 'E1', name: '退款测试场次', description: '', city: '', venue: '', dateRange: '', status: 'ON_SALE', cover: '', sessionCount: 1, category: '' })
  vi.spyOn(ticketApi, 'getSession').mockResolvedValue({ id: 'S1', eventId: 'E1', date: '', time: '', weekday: '', venue: '', gateTime: '', status: 'ON_SALE', priceFrom: 12800, availability: '充足' })
  vi.spyOn(ticketApi, 'getSeats').mockResolvedValue([])
  vi.spyOn(ticketApi, 'createRefund').mockImplementation(async () => {
    current.buyerRefund = { ...summaryFixture }
    current.refundEligibility = { eligible: false, deadline: '2026-10-01T11:30:00.000Z', reason: 'ALREADY_REQUESTED' }
    return { disposition: 'CREATED', refund: { ...refundFixture }, pollAfterMs: 2000 }
  })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.useRealTimers() })

async function open() {
  router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/orders/:orderId', component: OrderPage },
    { path: '/orders', name: 'orders', component: { template: '<div />' } },
    { path: '/events', name: 'events', component: { template: '<div />' } },
  ] })
  await router.push('/orders/O1')
  wrapper = mount(OrderPage, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
}
function page() { if (!wrapper) throw new Error('page not mounted'); return wrapper }
async function click(text: string) {
  const button = page().findAll('button').find((item) => item.text() === text)
  if (!button) throw new Error('missing button: ' + text)
  await button.trigger('click'); await flushPromises()
}
async function request() { await click('申请全额退款'); await click('确认退款') }
function refundText() { return page().get('.buyer-refund-panel').text() }
function processing() { current.buyerRefund = { ...summaryFixture } }

describe('Phase 12-2A buyer refund page', () => {
  it('shows the server-authorized amount and requires explicit confirmation; cancel does not POST', async () => {
    await open(); await click('申请全额退款')
    expect(page().get('dialog').element.open).toBe(true)
    expect(page().get('dialog').text()).toContain('整单 ¥128 将原路退款')
    expect(page().get('dialog').text()).toContain('完成前订单和座位权益仍然有效')
    expect(page().get('dialog').find('input').exists()).toBe(false)
    await click('暂不退款')
    expect(page().get('dialog').element.open).toBe(false)
    expect(ticketApi.createRefund).not.toHaveBeenCalled()
  })

  it.each(['PENDING_PAYMENT', 'EXPIRED', 'CANCELLED'] as const)('server rejects %s orders', async (status) => {
    current.status = status
    current.refundEligibility = { eligible: false, deadline: '2026-10-01T11:30:00.000Z', reason: 'ORDER_NOT_REFUNDABLE' }
    await open()
    expect(refundText()).toContain('订单当前不可退款')
    page().getComponent(BuyerRefundPanel).vm.$emit('request'); await flushPromises()
    expect(ticketApi.createRefund).not.toHaveBeenCalled()
  })

  it.each(['ALREADY_REQUESTED', 'REFUND_WINDOW_CLOSED'] as const)('does not submit when reason is %s', async (reason) => {
    current.refundEligibility = { eligible: false, deadline: '2026-10-01T11:30:00.000Z', reason }
    await open()
    expect(page().findAll('button').some((item) => item.text() === '申请全额退款')).toBe(false)
    page().getComponent(BuyerRefundPanel).vm.$emit('request'); await flushPromises()
    expect(ticketApi.createRefund).not.toHaveBeenCalled()
  })

  it('missing eligibility never invents permission', async () => {
    delete current.refundEligibility
    await open()
    page().getComponent(BuyerRefundPanel).vm.$emit('request'); await flushPromises()
    expect(ticketApi.createRefund).not.toHaveBeenCalled()
  })

  it('deadline disables an open confirmation locally without polling eligibility', async () => {
    current.refundEligibility = { eligible: true, deadline: new Date(Date.now() + 500).toISOString(), reason: null }
    await open(); await click('申请全额退款')
    await vi.advanceTimersByTimeAsync(500)
    expect(page().get('dialog').element.open).toBe(false)
    expect(refundText()).toContain('场次已经开始')
    page().getComponent(BuyerRefundPanel).vm.$emit('request'); await flushPromises()
    expect(ticketApi.createRefund).not.toHaveBeenCalled()
    expect(ticketApi.getOrder).toHaveBeenCalledOnce()
  })

  it('duplicate confirmations and repeated events produce at most one parallel POST', async () => {
    const pending = deferred<CreateRefundResult>()
    vi.mocked(ticketApi.createRefund).mockReturnValue(pending.promise)
    await open(); await click('申请全额退款')
    const confirm = page().findAll('button').find((item) => item.text() === '确认退款')
    await Promise.all([confirm?.trigger('click'), confirm?.trigger('click')])
    page().getComponent(BuyerRefundPanel).vm.$emit('request')
    page().getComponent(BuyerRefundPanel).vm.$emit('request')
    await flushPromises()
    expect(ticketApi.createRefund).toHaveBeenCalledExactlyOnceWith('O1')
    expect(page().findAll('button').find((item) => item.text() === '正在提交退款申请…')?.attributes('disabled')).toBeDefined()
    pending.resolve({ disposition: 'CREATED', refund: refundFixture, pollAfterMs: 2000 })
    await flushPromises()
    expect(refundText()).toContain('退款处理中，完成前订单和座位权益仍然有效。')
  })

  it.each([
    ['CREATED', 'PROCESSING'], ['REUSED_PROCESSING', 'PROCESSING'],
    ['REUSED_TERMINAL', 'SUCCEEDED'], ['REUSED_TERMINAL', 'FAILED'],
  ] as const)('renders %s by refund status %s', async (disposition, status) => {
    vi.mocked(ticketApi.createRefund).mockImplementation(async () => {
      current.buyerRefund = { ...summaryFixture, status }
      if (status === 'SUCCEEDED') current.status = 'CANCELLED'
      return { disposition, refund: { ...refundFixture, status }, pollAfterMs: 2000 }
    })
    await open(); await request()
    expect(refundText()).toContain(status === 'PROCESSING' ? '退款处理中，完成前订单和座位权益仍然有效。' : status === 'SUCCEEDED' ? '退款已完成，订单已取消，原座位已释放。' : '退款失败，订单和座位权益仍然有效。当前版本不支持再次自动退款。')
    if (status === 'SUCCEEDED') {
      expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
      expect(page().text()).not.toContain('支付成功')
    }
    expect(page().findAll('button').some((item) => item.text() === '申请全额退款')).toBe(false)
  })

  it.each(['PROCESSING', 'SUCCEEDED', 'FAILED'] as const)('initial load restores %s without a POST', async (status) => {
    current.buyerRefund = { ...summaryFixture, status, currency: 'usd' }
    if (status === 'SUCCEEDED') current.status = 'CANCELLED'
    await open()
    expect(refundText()).toContain('US$128.00')
    expect(ticketApi.createRefund).not.toHaveBeenCalled()
    expect(refundText()).toContain(status === 'PROCESSING' ? '退款处理中' : status === 'FAILED' ? '退款失败' : '退款已完成')
    await vi.advanceTimersByTimeAsync(4000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(status === 'PROCESSING' ? 3 : 1)
  })

  it('serial polling waits two seconds AFTER the preceding request completes', async () => {
    processing(); await open()
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await vi.advanceTimersByTimeAsync(1999)
    expect(ticketApi.getOrder).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(1)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(10000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    pending.resolve(structuredClone(current)); await flushPromises()
    await vi.advanceTimersByTimeAsync(1999)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(3)
  })

  it.each(['blur', 'hidden'] as const)('pauses on %s, coalesces visibility/focus, and resumes immediately', async (mode) => {
    processing(); await open()
    if (mode === 'blur') window.dispatchEvent(new Event('blur'))
    else { vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')) }
    await vi.advanceTimersByTimeAsync(6000)
    expect(ticketApi.getOrder).toHaveBeenCalledOnce()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(3)
  })

  it('an in-flight read completing after blur does not restart polling', async () => {
    processing(); await open()
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await vi.advanceTimersByTimeAsync(2000)
    window.dispatchEvent(new Event('blur'))
    pending.resolve(structuredClone(current)); await flushPromises()
    await vi.advanceTimersByTimeAsync(6000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
  })

  it.each(['focus-first', 'visibility-first'])('one activation remains one GET even when %s completes before the second event', async (order) => {
    processing(); await open()
    window.dispatchEvent(new Event('blur'))
    if (order === 'visibility-first') document.dispatchEvent(new Event('visibilitychange'))
    else window.dispatchEvent(new Event('focus'))
    await flushPromises()
    if (order === 'visibility-first') window.dispatchEvent(new Event('focus'))
    else document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
  })

  it('does not start polling when initially mounted in an unfocused window', async () => {
    vi.spyOn(document, 'hasFocus').mockReturnValue(false)
    processing(); await open()
    await vi.advanceTimersByTimeAsync(6000)
    expect(ticketApi.getOrder).toHaveBeenCalledOnce()
    window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
  })

  it.each(['SUCCEEDED', 'FAILED'] as const)('stops polling at %s and keeps the correct rights', async (status) => {
    processing(); await open()
    current.buyerRefund = { ...summaryFixture, status }
    if (status === 'SUCCEEDED') current.status = 'CANCELLED'
    await vi.advanceTimersByTimeAsync(2000)
    const reads = status === 'SUCCEEDED' ? 3 : 2
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(reads)
    await vi.advanceTimersByTimeAsync(6000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(reads)
    expect(page().text()).toContain(status === 'SUCCEEDED' ? '订单已取消' : '支付成功')
    expect(refundText()).toContain(status === 'SUCCEEDED' ? '原座位已释放' : '权益仍然有效。当前版本不支持再次自动退款')
  })

  it('transient polling errors do not turn PROCESSING into FAILED and are retried', async () => {
    processing(); await open()
    vi.mocked(ticketApi.getOrder).mockRejectedValueOnce(new Error('private provider error'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(page().text()).toContain('订单加载失败')
    expect(refundText()).toContain('退款处理中')
    expect(page().text()).not.toContain('private provider error')
    await vi.advanceTimersByTimeAsync(2000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(3)
    expect(page().text()).not.toContain('订单加载失败')
  })

  it.each(['PROCESSING', 'SUCCEEDED', 'FAILED'] as const)('lost POST recovers %s through GET Order', async (status) => {
    vi.mocked(ticketApi.createRefund).mockImplementation(async () => {
      current.buyerRefund = { ...summaryFixture, status }
      if (status === 'SUCCEEDED') current.status = 'CANCELLED'
      throw new Error('timeout')
    })
    await open(); await request()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    expect(page().text()).not.toContain('申请结果暂时无法确认')
    expect(refundText()).toContain(status === 'PROCESSING' ? '退款处理中' : status === 'SUCCEEDED' ? '退款已完成' : '退款失败')
  })

  it.each([false, true])('lost POST and recovery unavailable=%s shows uncertain result and permits a later retry', async (unavailable) => {
    await open()
    vi.mocked(ticketApi.createRefund).mockRejectedValueOnce(new Error('private error'))
    if (unavailable) vi.mocked(ticketApi.getOrder).mockRejectedValueOnce(new Error('offline'))
    await request()
    expect(refundText()).toContain('申请结果暂时无法确认，请刷新或稍后重试。')
    expect(refundText()).not.toContain('退款失败')
    expect(page().text()).not.toContain('private error')
    await request()
    expect(ticketApi.createRefund).toHaveBeenCalledTimes(2)
    expect(refundText()).toContain('退款处理中')
  })

  it.each(['ORDER_NOT_REFUNDABLE', 'REFUND_WINDOW_CLOSED'] as const)('refreshes eligibility once on %s with safe Chinese text', async (code) => {
    vi.mocked(ticketApi.createRefund).mockImplementation(async () => {
      current.refundEligibility = { eligible: false, deadline: '2026-10-01T11:30:00.000Z', reason: code }
      throw new TicketApiError('re_private provider error', code)
    })
    await open(); await request()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    expect(refundText()).toContain(code === 'ORDER_NOT_REFUNDABLE' ? '订单当前不可退款' : '场次已经开始')
    expect(page().text()).not.toContain('re_private')
  })

  it('404 clears the old order and uses the existing inaccessible-order page', async () => {
    vi.mocked(ticketApi.createRefund).mockRejectedValue(new TicketApiError('private', 'ORDER_NOT_FOUND'))
    await open(); await request()
    expect(page().text()).toContain('订单不存在或不可访问')
    expect(page().findComponent(BuyerRefundPanel).exists()).toBe(false)
  })

  it('manual refresh invalidates a late poll and still serializes GETs', async () => {
    processing(); await open()
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await vi.advanceTimersByTimeAsync(2000)
    await click('刷新状态')
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    current.buyerRefund = { ...summaryFixture, status: 'FAILED' }
    pending.resolve({ ...orderFixture }); await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(3)
    expect(refundText()).toContain('退款失败')
  })

  it.each(['poll', 'post', 'recovery'] as const)('ignores old %s responses after a route switch', async (kind) => {
    const old = deferred<TicketOrder>()
    const post = deferred<CreateRefundResult>()
    if (kind === 'poll') processing()
    await open()
    if (kind === 'poll') {
      vi.mocked(ticketApi.getOrder).mockReturnValueOnce(old.promise)
      await vi.advanceTimersByTimeAsync(2000)
    } else if (kind === 'post') {
      vi.mocked(ticketApi.createRefund).mockReturnValueOnce(post.promise)
      await request()
    } else {
      vi.mocked(ticketApi.createRefund).mockRejectedValueOnce(new Error('timeout'))
      vi.mocked(ticketApi.getOrder).mockReturnValueOnce(old.promise)
      await request()
    }
    current = { ...orderFixture, id: 'O2' }
    await router.push('/orders/O2'); await flushPromises()
    old.resolve({ ...orderFixture, buyerRefund: { ...summaryFixture, status: 'FAILED' } })
    post.reject(new Error('old POST response lost'))
    // The unused rejected promise must also be observed in poll/recovery cases.
    await post.promise.catch(() => {})
    await flushPromises()
    expect(page().text()).toContain('O2')
    expect(refundText()).not.toContain('退款失败')
    expect(refundText()).not.toContain('申请结果暂时无法确认')
    expect(vi.mocked(ticketApi.getOrder).mock.calls.at(-1)).toEqual(['O2'])
  })

  it('a late PROCESSING POST cannot overwrite a newer terminal GET', async () => {
    const post = deferred<CreateRefundResult>()
    vi.mocked(ticketApi.createRefund).mockReturnValueOnce(post.promise)
    await open(); await request()
    current = { ...current, status: 'CANCELLED', buyerRefund: { ...summaryFixture, status: 'SUCCEEDED' } }
    await click('刷新状态')
    post.resolve({ disposition: 'CREATED', refund: refundFixture, pollAfterMs: 2000 }); await flushPromises()
    expect(refundText()).toContain('退款已完成')
    expect(page().text()).not.toContain('支付成功')
  })

  it('ignores a successful POST that arrives after leaving its order', async () => {
    const post = deferred<CreateRefundResult>()
    vi.mocked(ticketApi.createRefund).mockReturnValueOnce(post.promise)
    await open(); await request()
    current = { ...orderFixture, id: 'O2' }
    await router.push('/orders/O2'); await flushPromises()
    post.resolve({ disposition: 'REUSED_TERMINAL', refund: { ...refundFixture, status: 'SUCCEEDED' }, pollAfterMs: 2000 })
    await flushPromises()
    expect(page().text()).toContain('O2')
    expect(refundText()).not.toContain('退款已完成')
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
  })

  it('unmount removes the deadline timer and ignores a pending POST completion', async () => {
    const post = deferred<CreateRefundResult>()
    vi.mocked(ticketApi.createRefund).mockReturnValueOnce(post.promise)
    await open(); await request()
    page().unmount(); wrapper = undefined
    expect(vi.getTimerCount()).toBe(0)
    post.resolve({ disposition: 'REUSED_TERMINAL', refund: { ...refundFixture, status: 'SUCCEEDED' }, pollAfterMs: 2000 })
    await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('a POST invalidating an active manual read eventually clears the loading state', async () => {
    await open()
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await click('刷新状态'); await request()
    pending.resolve({ ...orderFixture }); await flushPromises()
    expect(refundText()).toContain('退款处理中')
    expect(page().findAll('button').find((button) => button.text() === '刷新状态')?.attributes('disabled')).toBeUndefined()
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(3)
  })

  it('success POST never displays valid tickets while the authoritative order refresh is pending', async () => {
    await open()
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.createRefund).mockResolvedValue({ disposition: 'REUSED_TERMINAL', refund: { ...refundFixture, status: 'SUCCEEDED' }, pollAfterMs: 2000 })
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await request()
    expect(page().text()).not.toContain('支付成功')
    expect(page().text()).toContain('正在同步退款后的订单状态')
    pending.resolve({ ...current, status: 'CANCELLED', buyerRefund: { ...summaryFixture, status: 'SUCCEEDED' } }); await flushPromises()
    expect(page().text()).toContain('订单已取消')
  })

  it('unmount clears listeners and timers; late reads cannot issue follow-up work', async () => {
    const removeWindow = vi.spyOn(window, 'removeEventListener')
    const removeDocument = vi.spyOn(document, 'removeEventListener')
    processing(); await open()
    const pending = deferred<TicketOrder>()
    vi.mocked(ticketApi.getOrder).mockReturnValueOnce(pending.promise)
    await vi.advanceTimersByTimeAsync(2000)
    page().unmount(); wrapper = undefined
    expect(vi.getTimerCount()).toBe(0)
    expect(removeWindow.mock.calls.map(([name]) => name)).toEqual(expect.arrayContaining(['focus', 'blur']))
    expect(removeDocument.mock.calls.map(([name]) => name)).toContain('visibilitychange')
    pending.resolve({ ...current, status: 'CANCELLED', buyerRefund: { ...summaryFixture, status: 'SUCCEEDED' } })
    await flushPromises()
    window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(6000)
    expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
    expect(vi.getTimerCount()).toBe(0)
  })
})
