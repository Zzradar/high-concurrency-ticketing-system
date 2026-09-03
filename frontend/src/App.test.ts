import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import {
  resetMockData,
  setMockLatency,
  setMockPaymentSimulation,
  TicketApiError,
  ticketApi,
} from './api/ticketApi'
import type { CheckoutSession, TicketOrder } from './types'

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

async function settle(milliseconds = 10) {
  await vi.advanceTimersByTimeAsync(milliseconds)
  await flushPromises()
}

async function completeMock<T>(promise: Promise<T>, milliseconds = 10) {
  await settle(milliseconds)
  return promise
}

async function openSeatSelection(wrapper: VueWrapper, milliseconds = 10) {
  await settle(milliseconds)
  await wrapper.findAll('.text-button')[0]!.trigger('click')
  await settle(milliseconds)
  await wrapper.findAll('.session-card .primary-button')[0]!.trigger('click')
  await settle(milliseconds)
}

async function createPendingOrder(wrapper: VueWrapper) {
  await openSeatSelection(wrapper)
  const availableSeat = wrapper.find('button[aria-label^="A01，可选"]')
  expect(availableSeat.exists()).toBe(true)
  await availableSeat.trigger('click')
  await settle(10)

  const reserveButton = wrapper
    .findAll('button')
    .find((button) => button.text().includes('提交预订'))
  expect(reserveButton).toBeDefined()
  await reserveButton!.trigger('click')
  await settle(20)
  expect(wrapper.text()).toContain('待支付')
}

describe('ticket booking demo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetMockData()
    setMockLatency(1)
    setMockPaymentSimulation({ delayMilliseconds: 100, outcome: 'SUCCESS' })
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('completes event, session, seat, reservation and payment flow with fen formatting', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)

    const availableSeat = wrapper.find('button[aria-label^="A01，可选"]')
    await availableSeat.trigger('click')
    expect(wrapper.text()).toContain('¥1,280')
    await settle(10)

    const reserveButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('提交预订'))
    await reserveButton!.trigger('click')
    await settle(20)

    const payButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))
    expect(payButton).toBeDefined()
    await payButton!.trigger('click')
    await settle(1100)

    expect(wrapper.text()).toContain('支付成功')
    wrapper.unmount()
  })

  it('keeps cancel enabled during payment and reports the late-success refund', async () => {
    setMockPaymentSimulation({ delayMilliseconds: 2000, outcome: 'SUCCESS' })
    const wrapper = mount(App)
    await createPendingOrder(wrapper)

    const payButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))!
    await payButton.trigger('click')
    await settle(20)
    expect(wrapper.text()).toContain('支付处理中')

    const cancelButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('取消订单'))!
    expect(cancelButton.attributes('disabled')).toBeUndefined()
    await cancelButton.trigger('click')
    await settle(20)
    expect(wrapper.text()).toContain('订单已取消')

    await settle(2100)
    expect(wrapper.text()).toContain('订单已取消')
    expect(wrapper.text()).toContain('支付结果已处理，请查看自动退款通知')
    expect(wrapper.find('.notification-count').text()).toBe('2')

    await wrapper.find('.notification-button').trigger('click')
    const refundNotification = wrapper
      .findAll('.notification-item')
      .find((item) => item.text().includes('自动退款已完成'))!
    await refundNotification.trigger('click')
    await settle(10)
    expect(wrapper.find('.notification-count').text()).toBe('1')
    wrapper.unmount()
  })

  it('shows a failed payment as retryable', async () => {
    setMockPaymentSimulation({ delayMilliseconds: 100, outcome: 'FAILURE' })
    const wrapper = mount(App)
    await createPendingOrder(wrapper)

    const payButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))!
    await payButton.trigger('click')
    await settle(1100)

    expect(wrapper.text()).toContain('支付失败，订单仍有效时可以重新支付。')
    const retryButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))!
    expect(retryButton.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('stops payment polling after the component is unmounted', async () => {
    setMockPaymentSimulation({ delayMilliseconds: 5000, outcome: 'SUCCESS' })
    const attemptSpy = vi.spyOn(ticketApi, 'getPaymentAttempt')
    const wrapper = mount(App)
    await createPendingOrder(wrapper)
    const payButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))!
    await payButton.trigger('click')
    await settle(20)
    const callsBeforeUnmount = attemptSpy.mock.calls.length

    wrapper.unmount()
    await settle(3000)
    expect(attemptSpy).toHaveBeenCalledTimes(callsBeforeUnmount)
  })

  it('keeps the seat conflict message after refreshing seats', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)

    const competingReservation = ticketApi.createReservation(
      'ses-concert-1001',
      ['ses-concert-1001-A01'],
    )
    await settle()
    await competingReservation

    const reserveButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('提交预订'))
    await reserveButton!.trigger('click')
    await settle(20)

    expect(wrapper.text()).toContain('所选座位已发生变化，请重新选择。')
    wrapper.unmount()
  })

  it('keeps the payment result warning after refreshing the order', async () => {
    const wrapper = mount(App)
    await createPendingOrder(wrapper)
    vi.spyOn(ticketApi, 'payOrder').mockRejectedValueOnce(new Error('network timeout'))

    const payButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))
    await payButton!.trigger('click')
    await settle(20)

    expect(wrapper.text()).toContain('支付请求结果未知，正在重新查询订单。')
    expect(wrapper.text()).toContain('待支付')
    wrapper.unmount()
  })

  it('shows cancellation and timeout states in mock mode', async () => {
    const cancelWrapper = mount(App)
    await createPendingOrder(cancelWrapper)
    const cancelButton = cancelWrapper
      .findAll('button')
      .find((button) => button.text().includes('取消订单'))
    await cancelButton!.trigger('click')
    await settle(20)
    expect(cancelWrapper.text()).toContain('订单已取消')
    cancelWrapper.unmount()

    resetMockData()
    const expiryWrapper = mount(App)
    await createPendingOrder(expiryWrapper)
    const expireButton = expiryWrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟订单超时'))
    await expireButton!.trigger('click')
    await settle(20)
    expect(expiryWrapper.text()).toContain('订单已过期')
    expiryWrapper.unmount()
  })

  it('selects immediately, creates one checkout during rapid clicks, and catches up the checkpoint', async () => {
    setMockLatency(40)
    const createSpy = vi.spyOn(ticketApi, 'createCheckoutSession')
    const wrapper = mount(App)
    await openSeatSelection(wrapper, 100)

    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await wrapper.find('button[aria-label^="A02，可选"]').trigger('click')
    expect(wrapper.text()).toContain('A01')
    expect(wrapper.text()).toContain('A02')
    expect(createSpy).toHaveBeenCalledTimes(1)

    await settle(250)
    const checkout = await createSpy.mock.results[0]!.value
    const latest = await completeMock(ticketApi.getCheckoutSession(checkout.id), 50)
    expect(latest.seatIds).toEqual([
      'ses-concert-1001-A01',
      'ses-concert-1001-A02',
    ])
    wrapper.unmount()
  })

  it('preserves seat intent and refreshes after a temporary hold blocks creation', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    const getSeatsSpy = vi.spyOn(ticketApi, 'getSeats')
    vi.spyOn(ticketApi, 'createCheckoutSession').mockRejectedValueOnce(
      new TicketApiError('该座位正被其他购票会话暂时占用。', 'SEAT_TEMPORARILY_HELD'),
    )

    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(20)

    expect(wrapper.text()).toContain('该座位正被其他购票会话暂时占用。')
    expect(wrapper.text()).toContain('A01')
    expect(getSeatsSpy).toHaveBeenCalledWith('ses-concert-1001', undefined)
    wrapper.unmount()
  })

  it('treats a final temporary hold conflict as known and refreshes with C1', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)
    const locator = JSON.parse(sessionStorage.getItem('ticketing.currentCheckoutSession')!)
    const getSeatsSpy = vi.spyOn(ticketApi, 'getSeats')
    const getCheckoutSpy = vi.spyOn(ticketApi, 'getCheckoutSession')
    vi.spyOn(ticketApi, 'confirmCheckoutSession').mockRejectedValueOnce(
      new TicketApiError('该座位正被其他购票会话暂时占用。', 'SEAT_TEMPORARILY_HELD'),
    )

    await wrapper.find('.selection-panel .primary-button').trigger('click')
    await settle(20)

    expect(wrapper.text()).toContain('该座位正被其他购票会话暂时占用。')
    expect(wrapper.text()).toContain('A01')
    expect(getSeatsSpy).toHaveBeenCalledWith('ses-concert-1001', locator.checkoutSessionId)
    expect(getCheckoutSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('isolates pending checkout creation across sessions', async () => {
    const firstCreate = deferred<CheckoutSession>()
    const secondCreate = deferred<CheckoutSession>()
    const createSpy = vi
      .spyOn(ticketApi, 'createCheckoutSession')
      .mockImplementation((sessionId) =>
        sessionId === 'ses-concert-1001' ? firstCreate.promise : secondCreate.promise,
      )
    const wrapper = mount(App)
    await openSeatSelection(wrapper)

    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    expect(createSpy).toHaveBeenCalledTimes(1)
    await wrapper.find('.back-button').trigger('click')
    await wrapper.findAll('.session-card .primary-button')[1]!.trigger('click')
    await settle(10)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')

    expect(createSpy).toHaveBeenCalledTimes(2)
    expect(createSpy.mock.calls[1]![0]).toBe('ses-concert-1002')
    const now = new Date().toISOString()
    const firstCheckout: CheckoutSession = {
      id: 'CHK-S1-PENDING',
      userId: 'U-1001',
      sessionId: 'ses-concert-1001',
      seatIds: ['ses-concert-1001-A01'],
      status: 'SELECTING',
      revision: 0,
      createdAt: now,
      updatedAt: now,
    }
    const secondCheckout: CheckoutSession = {
      id: 'CHK-S2-CURRENT',
      userId: 'U-1001',
      sessionId: 'ses-concert-1002',
      seatIds: ['ses-concert-1002-A01'],
      status: 'SELECTING',
      revision: 0,
      createdAt: now,
      updatedAt: now,
    }

    firstCreate.resolve(firstCheckout)
    await flushPromises()
    expect(wrapper.text()).toContain('正在保存选座')
    expect(sessionStorage.getItem('ticketing.currentCheckoutSession')).toBeNull()

    secondCreate.resolve(secondCheckout)
    await flushPromises()
    expect(wrapper.text()).toContain('10月02日')
    expect(
      JSON.parse(sessionStorage.getItem('ticketing.currentCheckoutSession')!),
    ).toEqual({ checkoutSessionId: secondCheckout.id, sessionId: secondCheckout.sessionId })
    wrapper.unmount()
  })

  it('isolates pending seat synchronization across checkout sessions', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)
    const firstLocator = JSON.parse(
      sessionStorage.getItem('ticketing.currentCheckoutSession')!,
    )
    const firstSync = deferred<CheckoutSession>()
    const secondSync = deferred<CheckoutSession>()
    const replaceSpy = vi
      .spyOn(ticketApi, 'replaceCheckoutSessionSeats')
      .mockImplementation((checkoutId) =>
        checkoutId === firstLocator.checkoutSessionId
          ? firstSync.promise
          : secondSync.promise,
      )

    await wrapper.find('button[aria-label^="A02，可选"]').trigger('click')
    expect(replaceSpy).toHaveBeenCalledTimes(1)
    await wrapper.find('.back-button').trigger('click')
    await wrapper.findAll('.session-card .primary-button')[1]!.trigger('click')
    await settle(10)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)
    const secondLocator = JSON.parse(
      sessionStorage.getItem('ticketing.currentCheckoutSession')!,
    )
    await wrapper.find('button[aria-label^="A02，可选"]').trigger('click')

    expect(replaceSpy).toHaveBeenCalledTimes(2)
    expect(replaceSpy.mock.calls[1]![0]).toBe(secondLocator.checkoutSessionId)
    const now = new Date().toISOString()
    firstSync.resolve({
      id: firstLocator.checkoutSessionId,
      userId: 'U-1001',
      sessionId: 'ses-concert-1001',
      seatIds: ['ses-concert-1001-A01', 'ses-concert-1001-A02'],
      status: 'SELECTING',
      revision: 1,
      createdAt: now,
      updatedAt: now,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('正在后台同步最新选座')
    expect(
      JSON.parse(sessionStorage.getItem('ticketing.currentCheckoutSession')!).checkoutSessionId,
    ).toBe(secondLocator.checkoutSessionId)

    secondSync.resolve({
      id: secondLocator.checkoutSessionId,
      userId: 'U-1001',
      sessionId: 'ses-concert-1002',
      seatIds: ['ses-concert-1002-A01', 'ses-concert-1002-A02'],
      status: 'SELECTING',
      revision: 1,
      createdAt: now,
      updatedAt: now,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('10月02日')
    expect(wrapper.text()).not.toContain('正在后台同步最新选座')
    expect(
      JSON.parse(sessionStorage.getItem('ticketing.currentCheckoutSession')!).checkoutSessionId,
    ).toBe(secondLocator.checkoutSessionId)
    wrapper.unmount()
  })

  it('coalesces rapid changes behind one in-flight PUT', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)

    const originalReplace = ticketApi.replaceCheckoutSessionSeats.bind(ticketApi)
    const gate = deferred<void>()
    let first = true
    const replaceSpy = vi
      .spyOn(ticketApi, 'replaceCheckoutSessionSeats')
      .mockImplementation(async (...args) => {
        if (first) {
          first = false
          await gate.promise
        }
        return originalReplace(...args)
      })

    await wrapper.find('button[aria-label^="A02，可选"]').trigger('click')
    await wrapper.find('button[aria-label^="A04，可选"]').trigger('click')
    expect(replaceSpy).toHaveBeenCalledTimes(1)
    gate.resolve()
    await settle(50)
    expect(replaceSpy).toHaveBeenCalledTimes(2)
    const locator = JSON.parse(sessionStorage.getItem('ticketing.currentCheckoutSession')!)
    const latest = await completeMock(ticketApi.getCheckoutSession(locator.checkoutSessionId))
    expect(latest.seatIds).toEqual([
      'ses-concert-1001-A01',
      'ses-concert-1001-A02',
      'ses-concert-1001-A04',
    ])
    wrapper.unmount()
  })

  it('waits for the final synchronized seat checkpoint before confirm', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)

    const originalReplace = ticketApi.replaceCheckoutSessionSeats.bind(ticketApi)
    const gate = deferred<void>()
    let first = true
    const replaceSpy = vi
      .spyOn(ticketApi, 'replaceCheckoutSessionSeats')
      .mockImplementation(async (...args) => {
        if (first) {
          first = false
          await gate.promise
        }
        return originalReplace(...args)
      })
    const confirmSpy = vi.spyOn(ticketApi, 'confirmCheckoutSession')

    await wrapper.find('button[aria-label^="A02，可选"]').trigger('click')
    await wrapper.find('button[aria-label^="A04，可选"]').trigger('click')
    await wrapper.find('.selection-panel .primary-button').trigger('click')
    await settle(5)
    expect(confirmSpy).not.toHaveBeenCalled()

    gate.resolve()
    await settle(80)
    expect(replaceSpy).toHaveBeenCalledTimes(2)
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('待支付')
    wrapper.unmount()
  })

  it('stops confirm on a revision conflict and adopts the server checkpoint', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')
    await settle(10)
    const locator = JSON.parse(sessionStorage.getItem('ticketing.currentCheckoutSession')!)
    const current = await completeMock(
      ticketApi.getCheckoutSession(locator.checkoutSessionId),
    )
    const serverLatest: CheckoutSession = {
      ...current,
      seatIds: ['ses-concert-1001-A04'],
      revision: current.revision + 1,
    }
    const gate = deferred<never>()
    vi.spyOn(ticketApi, 'replaceCheckoutSessionSeats').mockReturnValue(gate.promise)
    vi.spyOn(ticketApi, 'getCheckoutSession').mockResolvedValue(serverLatest)
    const confirmSpy = vi.spyOn(ticketApi, 'confirmCheckoutSession')

    await wrapper.find('button[aria-label^="A02，可选"]').trigger('click')
    await wrapper.find('.selection-panel .primary-button').trigger('click')
    gate.reject(
      new TicketApiError('该购票会话已在其他页面发生修改。', 'CHECKOUT_SESSION_VERSION_CONFLICT'),
    )
    await settle(20)

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('该购票会话已在其他页面发生修改')
    expect(wrapper.text()).toContain('A04')
    expect(wrapper.text()).not.toContain('A01\n')
    wrapper.unmount()
  })

  it('recovers a locator and preserves an unavailable selected seat until explicit removal', async () => {
    const checkout = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A08']),
    )
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: checkout.id, sessionId: checkout.sessionId }),
    )
    const getSpy = vi.spyOn(ticketApi, 'getCheckoutSession')
    const getSeatsSpy = vi.spyOn(ticketApi, 'getSeats')
    const wrapper = mount(App)
    await openSeatSelection(wrapper)

    expect(getSpy).toHaveBeenCalledWith(checkout.id)
    expect(getSeatsSpy).toHaveBeenCalledWith(checkout.sessionId, checkout.id)
    expect(wrapper.text()).toContain('当前不可用')
    const remove = wrapper.find('button[aria-label="移除座位 A08"]')
    expect(remove.attributes('disabled')).toBeUndefined()
    await remove.trigger('click')
    await settle(10)
    expect(wrapper.text()).not.toContain('当前不可用')
    wrapper.unmount()
  })

  it('falls back from an invalid locator to explicit recoverable selection', async () => {
    const first = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const second = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A02']),
    )
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: 'missing', sessionId: 'ses-concert-1001' }),
    )
    const wrapper = mount(App)
    await openSeatSelection(wrapper)

    expect(wrapper.text()).toContain('发现可继续的购票会话')
    expect(wrapper.text()).toContain(first.id.slice(0, 18))
    expect(wrapper.text()).toContain(second.id.slice(0, 18))
    expect(wrapper.findAll('.recoverable-item')).toHaveLength(2)
    const abandonSpy = vi.spyOn(ticketApi, 'abandonCheckoutSession')
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始新的选座'))!
      .trigger('click')
    expect(wrapper.findAll('.recoverable-item')).toHaveLength(0)
    expect(abandonSpy).not.toHaveBeenCalled()
    wrapper.unmount()

    const recoveryWrapper = mount(App)
    await openSeatSelection(recoveryWrapper)
    const firstItem = recoveryWrapper
      .findAll('.recoverable-item')
      .find((item) => item.text().includes(first.id.slice(0, 18)))
    await firstItem!.find('.secondary-button').trigger('click')
    await settle(10)
    expect(recoveryWrapper.text()).toContain('A01')
    recoveryWrapper.unmount()
  })

  it('re-reads a stale recoverable candidate and enters latest SUBMITTING state', async () => {
    const candidate = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const latest: CheckoutSession = {
      ...candidate,
      status: 'SUBMITTING',
      revision: candidate.revision + 1,
    }
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    const getSpy = vi.spyOn(ticketApi, 'getCheckoutSession').mockResolvedValue(latest)

    await wrapper.find('.recoverable-item .secondary-button').trigger('click')
    await flushPromises()

    expect(getSpy).toHaveBeenCalledWith(candidate.id)
    expect(wrapper.text()).toContain('正在确认预订')
    expect(wrapper.find('button[aria-label^="A01，"]').attributes('disabled')).toBeDefined()
    expect(sessionStorage.getItem('ticketing.currentCheckoutSession')).toContain(candidate.id)
    wrapper.unmount()
  })

  it('re-reads a stale recoverable candidate and enters latest RESERVED order', async () => {
    const candidate = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const order: TicketOrder = {
      id: 'TKT-LATEST-RESERVED',
      reservationId: 'RSV-LATEST-RESERVED',
      eventId: 'evt-concert-2026',
      sessionId: candidate.sessionId,
      seatIds: candidate.seatIds,
      status: 'PENDING_PAYMENT',
      totalAmount: 128000,
      expiresAt: new Date(Date.now() + 900000).toISOString(),
      createdAt: new Date().toISOString(),
    }
    const latest: CheckoutSession = {
      ...candidate,
      status: 'RESERVED',
      revision: candidate.revision + 1,
      reservationId: order.reservationId,
      order,
    }
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    const getSpy = vi.spyOn(ticketApi, 'getCheckoutSession').mockResolvedValue(latest)

    await wrapper.find('.recoverable-item .secondary-button').trigger('click')
    await settle(10)

    expect(getSpy).toHaveBeenCalledWith(candidate.id)
    expect(wrapper.text()).toContain('待支付')
    expect(wrapper.text()).not.toContain('发现可继续的购票会话')
    wrapper.unmount()
  })

  it.each(['ABANDONED', 'NOT_FOUND'] as const)(
    'does not apply a stale recoverable candidate when latest is %s',
    async (outcome) => {
      const candidate = await completeMock(
        ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
      )
      const wrapper = mount(App)
      await openSeatSelection(wrapper)
      const getSpy = vi.spyOn(ticketApi, 'getCheckoutSession')
      if (outcome === 'ABANDONED') {
        getSpy.mockResolvedValue({ ...candidate, status: 'ABANDONED' })
      } else {
        getSpy.mockRejectedValue(
          new TicketApiError('未找到该购票会话。', 'CHECKOUT_SESSION_NOT_FOUND'),
        )
      }

      await wrapper.find('.recoverable-item .secondary-button').trigger('click')
      await flushPromises()

      expect(getSpy).toHaveBeenCalledWith(candidate.id)
      expect(wrapper.text()).toContain('该购票会话已不可恢复')
      expect(wrapper.findAll('.recoverable-item')).toHaveLength(0)
      expect(wrapper.text()).toContain('还没有选择座位')
      expect(sessionStorage.getItem('ticketing.currentCheckoutSession')).toBeNull()
      wrapper.unmount()
    },
  )

  it('polls SUBMITTING to RESERVED and clears polling after leaving the session', async () => {
    const checkout = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const submitting: CheckoutSession = { ...checkout, status: 'SUBMITTING' }
    const order: TicketOrder = {
      id: 'TKT-POLL',
      reservationId: 'RSV-POLL',
      eventId: 'evt-concert-2026',
      sessionId: checkout.sessionId,
      seatIds: checkout.seatIds,
      status: 'PENDING_PAYMENT',
      totalAmount: 128000,
      expiresAt: new Date(Date.now() + 900000).toISOString(),
      createdAt: new Date().toISOString(),
    }
    const reserved: CheckoutSession = {
      ...submitting,
      status: 'RESERVED',
      reservationId: order.reservationId,
      order,
    }
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: checkout.id, sessionId: checkout.sessionId }),
    )
    const getSpy = vi
      .spyOn(ticketApi, 'getCheckoutSession')
      .mockResolvedValueOnce(submitting)
      .mockResolvedValueOnce(submitting)
      .mockResolvedValueOnce(reserved)
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    expect(wrapper.text()).toContain('正在确认预订')
    await settle(2000)
    expect(wrapper.text()).toContain('待支付')
    const callsAtOrder = getSpy.mock.calls.length
    wrapper.unmount()
    await settle(5000)
    expect(getSpy).toHaveBeenCalledTimes(callsAtOrder)
  })

  it('wakes and stops a pending poll wait when leaving seat selection', async () => {
    const checkout = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const submitting: CheckoutSession = { ...checkout, status: 'SUBMITTING' }
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: checkout.id, sessionId: checkout.sessionId }),
    )
    const getSpy = vi.spyOn(ticketApi, 'getCheckoutSession').mockResolvedValue(submitting)
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await settle(10)
    expect(wrapper.text()).toContain('正在确认预订')

    await wrapper.find('.back-button').trigger('click')
    await flushPromises()
    const callsAfterLeaving = getSpy.mock.calls.length
    await settle(20000)

    expect(getSpy).toHaveBeenCalledTimes(callsAfterLeaving)
    expect(wrapper.text()).not.toContain('确认结果暂时无法确定')
    wrapper.unmount()
  })

  it('does not let a stopped poll clear the next checkout poll wait', async () => {
    const first = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const second = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1002', ['ses-concert-1002-A01']),
    )
    const firstSubmitting: CheckoutSession = { ...first, status: 'SUBMITTING' }
    const secondSubmitting: CheckoutSession = { ...second, status: 'SUBMITTING' }
    const secondSelecting: CheckoutSession = { ...second, status: 'SELECTING' }
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: first.id, sessionId: first.sessionId }),
    )
    let secondCalls = 0
    const getSpy = vi.spyOn(ticketApi, 'getCheckoutSession').mockImplementation(async (id) => {
      if (id === first.id) return firstSubmitting
      secondCalls += 1
      return secondCalls < 3 ? secondSubmitting : secondSelecting
    })
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await settle(10)
    expect(wrapper.text()).toContain('正在确认预订')

    await wrapper.find('.back-button').trigger('click')
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: second.id, sessionId: second.sessionId }),
    )
    await wrapper.findAll('.session-card .primary-button')[1]!.trigger('click')
    await settle(10)
    expect(wrapper.text()).toContain('正在确认预订')
    const firstCallsAfterSwitch = getSpy.mock.calls.filter(([id]) => id === first.id).length

    await settle(2000)

    expect(secondCalls).toBe(3)
    expect(wrapper.text()).toContain('提交预订')
    expect(wrapper.text()).not.toContain('正在确认预订')
    expect(getSpy.mock.calls.filter(([id]) => id === first.id)).toHaveLength(
      firstCallsAfterSwitch,
    )
    wrapper.unmount()
  })

  it('shows an uncertain result after 15 seconds and retries the original confirm', async () => {
    const checkout = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const submitting: CheckoutSession = { ...checkout, status: 'SUBMITTING' }
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: checkout.id, sessionId: checkout.sessionId }),
    )
    vi.spyOn(ticketApi, 'getCheckoutSession').mockResolvedValue(submitting)
    const confirmSpy = vi
      .spyOn(ticketApi, 'confirmCheckoutSession')
      .mockRejectedValue(new Error('still unknown'))
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await settle(15000)

    expect(wrapper.text()).toContain('确认结果暂时无法确定')
    const retry = wrapper
      .findAll('button')
      .find((button) => button.text().includes('继续原确认'))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await settle(10)
    expect(confirmSpy).toHaveBeenCalledWith(checkout.id)
    wrapper.unmount()
  })

  it('stops SUBMITTING polling when the server has explicitly returned to SELECTING', async () => {
    const checkout = await completeMock(
      ticketApi.createCheckoutSession('ses-concert-1001', ['ses-concert-1001-A01']),
    )
    const submitting: CheckoutSession = { ...checkout, status: 'SUBMITTING' }
    const selecting: CheckoutSession = { ...checkout, status: 'SELECTING' }
    sessionStorage.setItem(
      'ticketing.currentCheckoutSession',
      JSON.stringify({ checkoutSessionId: checkout.id, sessionId: checkout.sessionId }),
    )
    const getSpy = vi
      .spyOn(ticketApi, 'getCheckoutSession')
      .mockResolvedValueOnce(submitting)
      .mockResolvedValueOnce(selecting)
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await settle(10)

    expect(wrapper.text()).toContain('提交预订')
    expect(wrapper.text()).not.toContain('正在确认预订')
    const callsAfterSelecting = getSpy.mock.calls.length
    await settle(5000)
    expect(getSpy).toHaveBeenCalledTimes(callsAfterSelecting)
    wrapper.unmount()
  })
})
