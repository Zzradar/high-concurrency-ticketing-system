import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import OrderPage from './OrderPage.vue'
import StripePaymentPanel from '../components/StripePaymentPanel.vue'
import { ticketApi } from '../api/ticketApi'
import type { PaymentAttempt, PaymentAction, TicketOrder } from '../types'

const fake = vi.hoisted(() => {
  const instances: { handlers: Record<string, (event?: any) => void>; mount: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn> }[] = []
  const create = vi.fn(() => {
    const instance = { handlers: {} as Record<string, (event?: any) => void>, mount: vi.fn(), destroy: vi.fn(), on: vi.fn() }
    instance.on.mockImplementation((name: string, handler: (event?: any) => void) => { instance.handlers[name] = handler })
    instances.push(instance)
    return instance
  })
  const elements = vi.fn(() => ({ create }))
  const confirmPayment = vi.fn()
  const loadStripe = vi.fn(async () => ({ elements, confirmPayment }))
  return { instances, create, elements, confirmPayment, loadStripe }
})
vi.mock('@stripe/stripe-js', () => ({ loadStripe: fake.loadStripe }))

const secret = 'pi_test_secret_memoryonly'
const action: PaymentAction = { provider: 'stripe', type: 'CLIENT_CONFIRM', clientSecret: secret }
let currentOrder: TicketOrder
let attempt: PaymentAttempt
let wrapper: VueWrapper | undefined
let testRouter: ReturnType<typeof createRouter>

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubEnv('VITE_STRIPE_PUBLISHABLE_KEY', 'pk_test_unit')
  vi.clearAllMocks()
  fake.instances.length = 0
  fake.confirmPayment.mockResolvedValue({ paymentIntent: { status: 'succeeded' } })
  currentOrder = { buyerRefund: null, id: 'O1', reservationId: 'R1', eventId: 'E1', sessionId: 'S1', seatIds: [], status: 'PENDING_PAYMENT', totalAmount: 100, createdAt: new Date().toISOString(), expiresAt: new Date(Date.now() + 900000).toISOString() }
  attempt = { id: 'P1', orderId: 'O1', provider: 'stripe', status: 'PROCESSING', startedAt: new Date().toISOString(), processingDeadline: new Date(Date.now() + 10000).toISOString() }
  vi.spyOn(ticketApi, 'getOrder').mockImplementation(async () => ({ ...currentOrder }))
  vi.spyOn(ticketApi, 'getSession').mockResolvedValue({ id: 'S1', eventId: 'E1', date: '', time: '', weekday: '', venue: '', gateTime: '', status: 'ON_SALE', priceFrom: 100, availability: '充足' })
  vi.spyOn(ticketApi, 'getEvent').mockResolvedValue({ id: 'E1', name: 'Test Event', description: '', city: '', venue: '', dateRange: '', status: 'ON_SALE', cover: '', sessionCount: 1, category: '' })
  vi.spyOn(ticketApi, 'getSeats').mockResolvedValue([])
  vi.spyOn(ticketApi, 'getPaymentAttempt').mockImplementation(async () => ({ ...attempt }))
  vi.spyOn(ticketApi, 'payOrder').mockImplementation(async () => ({ disposition: 'STARTED_NEW', order: { ...currentOrder }, paymentAttempt: { ...attempt }, paymentAction: action }))
  vi.spyOn(ticketApi, 'cancelOrder').mockImplementation(async () => {
    currentOrder = { ...currentOrder, status: 'CANCELLED' }
    return { disposition: 'CANCELLED_NOW', order: { ...currentOrder } }
  })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  vi.useRealTimers()
})

async function open(query = '') {
  testRouter = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/orders/:orderId', component: OrderPage },
    { path: '/orders', name: 'orders', component: { template: '<div />' } },
    { path: '/events', name: 'events', component: { template: '<div />' } },
  ] })
  await testRouter.push('/orders/O1' + query)
  wrapper = mount(OrderPage, { global: { plugins: [testRouter] } })
  await flushPromises()
  return wrapper
}
async function start() {
  await wrapper!.get('.order-pay-button').trigger('click')
  await flushPromises()
  await flushPromises()
}
async function ready() {
  const element = fake.instances.at(-1)!
  element.handlers.ready!()
  element.handlers.change!({ complete: true })
  await flushPromises()
}
async function confirm() {
  await ready()
  await wrapper!.get('.stripe-payment-panel button').trigger('click')
  await flushPromises()
}

describe('Phase11 payment page', () => {
  it('destroys and recreates Elements for a different clientSecret and on unmount', async () => {
    wrapper = mount(StripePaymentPanel, { props: { clientSecret: secret, paymentAttemptId: 'P1', orderId: 'O1' } })
    await flushPromises(); await flushPromises()
    await wrapper.setProps({ clientSecret: 'pi_second_secret_test', paymentAttemptId: 'P2' })
    await flushPromises()
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(fake.elements).toHaveBeenLastCalledWith({ clientSecret: 'pi_second_secret_test' })
    wrapper.unmount(); wrapper = undefined
    expect(fake.instances[1]!.destroy).toHaveBeenCalledOnce()
  })

  it('Element loaderror shows a safe error and leaves confirmation disabled', async () => {
    await open(); await start()
    fake.instances[0]!.handlers.loaderror!({ error: { message: secret } })
    await flushPromises()
    expect(wrapper!.text()).toContain('支付组件暂时无法加载')
    expect(wrapper!.text()).not.toContain(secret)
    expect(wrapper!.get('.stripe-payment-panel button').attributes('disabled')).toBeDefined()
  })

  it('late polling reads cannot overwrite a successful cancellation', async () => {
    let resolve!: (value: PaymentAttempt) => void
    vi.mocked(ticketApi.getPaymentAttempt).mockImplementation(() => new Promise((done) => { resolve = done }))
    await open(); await start(); await confirm()
    await wrapper!.findAll('button').find((b) => b.text() === '取消订单')!.trigger('click')
    await flushPromises()
    resolve({ ...attempt, status: 'SUCCEEDED' }); await flushPromises()
    expect(wrapper!.text()).toContain('订单已取消')
    expect(wrapper!.text()).not.toContain('支付成功')
  })

  it('simulation polls directly without loading Stripe and preserves cancellation', async () => {
    vi.stubEnv('VITE_STRIPE_PUBLISHABLE_KEY', '')
    vi.mocked(ticketApi.payOrder).mockResolvedValue({ disposition: 'STARTED_NEW', order: currentOrder, paymentAttempt: { ...attempt, provider: 'simulation' }, paymentAction: null })
    await open(); await start()
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledWith('P1')
    expect(fake.loadStripe).not.toHaveBeenCalled()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
    expect(wrapper!.findAll('button').find((b) => b.text() === '取消订单')!.attributes('disabled')).toBeUndefined()
  })

  it('prepares a Payment Element before explicit confirmation and waits for Backend after success', async () => {
    await open(); await start()
    expect(fake.elements).toHaveBeenCalledWith({ clientSecret: secret })
    expect(fake.create).toHaveBeenCalledWith('payment')
    expect(fake.instances[0]!.mount).toHaveBeenCalledOnce()
    expect(fake.confirmPayment).not.toHaveBeenCalled()
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
    expect(wrapper!.get('.stripe-payment-panel button').attributes('disabled')).toBeDefined()
    await confirm()
    expect(fake.confirmPayment).toHaveBeenCalledWith(expect.objectContaining({ redirect: 'if_required', confirmParams: { return_url: `${window.location.origin}/orders/O1?paymentReturn=1&paymentAttemptId=P1` } }))
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledWith('P1')
    expect(wrapper!.text()).toContain('待支付')
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(true)
    currentOrder.status = 'PAID'; attempt.status = 'SUCCEEDED'
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper!.text()).toContain('支付成功')
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
  })

  it('missing publishable key retains the attempt without another pay request', async () => {
    vi.stubEnv('VITE_STRIPE_PUBLISHABLE_KEY', '')
    await open(); await start()
    expect(wrapper!.text()).toContain('缺少 VITE_STRIPE_PUBLISHABLE_KEY')
    expect(wrapper!.text()).toContain('P1')
    expect(fake.loadStripe).not.toHaveBeenCalled()
    await start()
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
  })

  it.each([{ ...action, provider: 'other' }, { ...action, type: 'OTHER' }, { ...action, clientSecret: '' }])('safely rejects unsupported/invalid action %j', async (paymentAction) => {
    vi.mocked(ticketApi.payOrder).mockResolvedValue({ disposition: 'STARTED_NEW', order: currentOrder, paymentAttempt: attempt, paymentAction })
    await open(); await start()
    expect(wrapper!.text()).toMatch(/暂不受此客户端支持|支付组件数据无效/)
    expect(fake.elements).not.toHaveBeenCalled()
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('支付渠道处理中')
  })

  it('validation error remains local, redacts secrets, and allows correction', async () => {
    fake.confirmPayment.mockResolvedValue({ error: { type: 'validation_error', message: '请检查支付信息 ' + secret } })
    await open(); await start(); await confirm()
    expect(wrapper!.text()).toContain('请检查支付信息')
    expect(wrapper!.html()).not.toContain(secret)
    expect(wrapper!.get('.stripe-payment-panel button').attributes('disabled')).toBeUndefined()
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('待支付')
    expect(wrapper!.text()).toContain('支付渠道处理中')
    expect(fake.instances[0]!.destroy).not.toHaveBeenCalled()
    fake.confirmPayment.mockResolvedValue({ paymentIntent: { status: 'succeeded' } })
    await wrapper!.get('.stripe-payment-panel button').trigger('click')
    await flushPromises()
    expect(fake.confirmPayment).toHaveBeenCalledTimes(2)
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
  })

  it.each(['throw', 'api_error', 'empty'])('recovers uncertain %s without another POST', async (kind) => {
    if (kind === 'throw') fake.confirmPayment.mockRejectedValue(new Error(secret))
    else fake.confirmPayment.mockResolvedValue(kind === 'empty' ? {} : { error: { type: 'api_error', message: secret } })
    await open(); await start(); await confirm()
    expect(wrapper!.text()).toContain('支付结果暂未确认，正在同步服务器状态')
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledWith('P1')
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
    expect(wrapper!.text()).not.toContain(secret)
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(true)
    expect(fake.instances[0]!.destroy).not.toHaveBeenCalled()
    expect(wrapper!.get('.stripe-payment-panel button').attributes('disabled')).toBeDefined()
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeDefined()
  })

  it('cancel destroys the Element and ignores an unresolved redirect/3DS confirmation', async () => {
    let resolve!: (value: unknown) => void
    fake.confirmPayment.mockImplementation(() => new Promise((done) => { resolve = done }))
    await open(); await start(); await confirm()
    expect(wrapper!.text()).toContain('正在与支付渠道确认')
    await wrapper!.findAll('button').find((b) => b.text() === '取消订单')!.trigger('click')
    await flushPromises()
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(ticketApi.cancelOrder).toHaveBeenCalledWith('O1')
    resolve({ paymentIntent: { status: 'succeeded' } })
    await flushPromises()
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('订单已取消')
  })

  it('does not interpret more than 10 seconds of user authentication as frontend failure', async () => {
    fake.confirmPayment.mockReturnValue(new Promise(() => {}))
    await open(); await start(); await confirm()
    await vi.advanceTimersByTimeAsync(11000)
    expect(wrapper!.text()).toContain('正在与支付渠道确认')
    expect(wrapper!.text()).toContain('待支付')
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
  })

  it('polling stops after 15 seconds with an undetermined result', async () => {
    await open(); await start(); await confirm()
    await vi.advanceTimersByTimeAsync(15000)
    expect(wrapper!.text()).toContain('支付结果仍在处理中，请稍后刷新订单和通知')
    const reads = vi.mocked(ticketApi.getPaymentAttempt).mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(reads)
    expect(wrapper!.text()).not.toContain('支付失败')
  })

  it.each(['PAID', 'CANCELLED', 'EXPIRED'] as const)('terminal %s removes the active Element on refresh', async (status) => {
    await open(); await start()
    currentOrder.status = status
    window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
  })

  it('ALREADY_PAID never mounts a returned action', async () => {
    vi.mocked(ticketApi.payOrder).mockResolvedValue({ disposition: 'ALREADY_PAID', order: { ...currentOrder, status: 'PAID' }, paymentAttempt: attempt, paymentAction: action })
    await open(); await start()
    expect(fake.elements).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('支付成功')
  })

  it('reopen explicitly recovers the same attempt through REUSED_PROCESSING', async () => {
    await open(); await start()
    wrapper!.unmount(); wrapper = undefined
    vi.mocked(ticketApi.payOrder).mockResolvedValue({ disposition: 'REUSED_PROCESSING', order: currentOrder, paymentAttempt: attempt, paymentAction: action })
    await open()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
    await start()
    expect(fake.instances).toHaveLength(2)
    expect(wrapper!.text()).toContain('P1')
    expect(ticketApi.payOrder).toHaveBeenCalledTimes(2)
  })

  it('payment actions never write storage, console, notifications or secret-bearing Backend arguments', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const logs = [vi.spyOn(console, 'log'), vi.spyOn(console, 'error'), vi.spyOn(console, 'warn')]
    const signals: string[] = []
    const listener = (event: Event) => signals.push((event as CustomEvent<string>).detail)
    window.addEventListener('ticketing:notice', listener)
    try {
      await open(); await start(); await confirm()
      expect(storage).not.toHaveBeenCalled()
      for (const log of logs) expect(JSON.stringify(log.mock.calls)).not.toContain(secret)
      expect(signals.join()).not.toContain(secret)
      expect(JSON.stringify(vi.mocked(ticketApi.payOrder).mock.calls)).not.toContain(secret)
      expect(JSON.stringify(vi.mocked(ticketApi.getPaymentAttempt).mock.calls)).not.toContain(secret)
    } finally { window.removeEventListener('ticketing:notice', listener) }
  })
})

describe('declined payment recovery', () => {
  async function refresh() {
    await wrapper!.findAll('button').find((button) => button.text() === '刷新状态')!.trigger('click')
    await flushPromises()
  }

  it('card_error waits through PROCESSING twice, cleans FAILED A, then creates B and reaches PAID', async () => {
    fake.confirmPayment.mockResolvedValue({ error: { type: 'card_error', code: 'card_declined', message: '您的卡被拒绝。' } })
    await open(); await start(); await confirm()
    expect(wrapper!.text()).toContain('您的卡被拒绝')
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(1)
    await start()
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
    expect(fake.instances[0]!.destroy).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(2)
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeDefined()
    expect(wrapper!.get('.stripe-payment-panel button').attributes('disabled')).toBeDefined()

    attempt = { ...attempt, status: 'FAILED', failureReason: 'card_declined' }
    const orderReads = vi.mocked(ticketApi.getOrder).mock.calls.length
    await vi.advanceTimersByTimeAsync(1000)
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeUndefined()
    expect(wrapper!.text()).toContain('待支付')
    expect(wrapper!.text()).not.toContain('您的卡被拒绝')
    expect(vi.mocked(ticketApi.getOrder).mock.calls.length).toBeGreaterThan(orderReads)
    const readsAfterFailure = vi.mocked(ticketApi.getPaymentAttempt).mock.calls.length
    await vi.advanceTimersByTimeAsync(2000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledTimes(readsAfterFailure)

    const secondSecret = 'pi_second_secret_fake'
    attempt = { ...attempt, id: 'P2', status: 'PROCESSING', failureReason: undefined }
    vi.mocked(ticketApi.payOrder).mockResolvedValue({ disposition: 'STARTED_NEW', order: currentOrder, paymentAttempt: attempt, paymentAction: { ...action, clientSecret: secondSecret } })
    await start()
    expect(ticketApi.payOrder).toHaveBeenCalledTimes(2)
    expect(ticketApi.payOrder).toHaveBeenLastCalledWith('O1')
    expect(wrapper!.findComponent(StripePaymentPanel).props('paymentAttemptId')).toBe('P2')
    expect(fake.elements).toHaveBeenLastCalledWith({ clientSecret: secondSecret })
    expect(fake.instances).toHaveLength(2)
    fake.confirmPayment.mockResolvedValue({ paymentIntent: { status: 'succeeded' } })
    await confirm()
    expect(ticketApi.getPaymentAttempt).toHaveBeenLastCalledWith('P2')
    attempt.status = 'SUCCEEDED'; currentOrder.status = 'PAID'
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper!.text()).toContain('支付成功')
    expect(fake.instances[1]!.destroy).toHaveBeenCalledOnce()
    expect(ticketApi.payOrder).toHaveBeenCalledTimes(2)
  })

  it.each(['FAILED', 'SUCCEEDED'] as const)('unknown result retains action until Backend %s', async (status) => {
    fake.confirmPayment.mockRejectedValue(new Error('network unavailable'))
    await open(); await start(); await confirm()
    await vi.advanceTimersByTimeAsync(15000)
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(true)
    expect(fake.instances[0]!.destroy).not.toHaveBeenCalled()
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeDefined()
    expect(wrapper!.get('.stripe-payment-panel button').attributes('disabled')).toBeDefined()
    await start()
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
    attempt.status = status
    if (status === 'SUCCEEDED') currentOrder.status = 'PAID'
    await refresh()
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
    if (status === 'FAILED') expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeUndefined()
    else expect(wrapper!.text()).toContain('支付成功')
    expect(wrapper!.text()).not.toContain('支付结果仍在处理中')
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
  })

  it('refresh status reads the current failed Attempt even while Order stays pending', async () => {
    await open(); await start()
    attempt.status = 'FAILED'
    await refresh()
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledExactlyOnceWith('P1')
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(false)
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeUndefined()
    await refresh()
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
  })

  it('card_error can converge to Backend success instead of being forced to failure', async () => {
    fake.confirmPayment.mockResolvedValue({ error: { type: 'card_error', message: '卡片错误' } })
    await open(); await start(); await confirm()
    attempt.status = 'SUCCEEDED'; currentOrder.status = 'PAID'
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper!.text()).toContain('支付成功')
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
  })

  it('unavailable Attempt reads preserve action and do not unlock another pay', async () => {
    fake.confirmPayment.mockResolvedValue({ error: { type: 'card_error', message: '卡被拒绝' } })
    vi.mocked(ticketApi.getPaymentAttempt).mockRejectedValue(new Error('unavailable'))
    await open(); await start(); await confirm()
    await vi.advanceTimersByTimeAsync(15000)
    await refresh()
    expect(wrapper!.findComponent(StripePaymentPanel).exists()).toBe(true)
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeDefined()
    expect(ticketApi.payOrder).toHaveBeenCalledOnce()
  })

  it('late old Attempt reads cannot replace B or destroy its Element', async () => {
    fake.confirmPayment.mockResolvedValue({ error: { type: 'card_error', message: '拒付' } })
    let resolveOld!: (value: PaymentAttempt) => void
    vi.mocked(ticketApi.getPaymentAttempt).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    await open(); await start(); await confirm()
    const failed = { ...attempt, status: 'FAILED' as const }
    attempt = failed
    await refresh()
    attempt = { ...attempt, id: 'P2', status: 'PROCESSING' }
    vi.mocked(ticketApi.payOrder).mockResolvedValue({ disposition: 'STARTED_NEW', order: currentOrder, paymentAttempt: attempt, paymentAction: { ...action, clientSecret: 'pi_B_secret_fake' } })
    await start()
    resolveOld(failed); await flushPromises()
    expect(wrapper!.findComponent(StripePaymentPanel).props('paymentAttemptId')).toBe('P2')
    expect(fake.instances[1]!.destroy).not.toHaveBeenCalled()
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
  })

  it('FAILED cleanup keeps payment blocked if the final Order refresh fails', async () => {
    await open(); await start()
    attempt.status = 'FAILED'
    vi.mocked(ticketApi.getOrder).mockResolvedValueOnce(currentOrder).mockRejectedValueOnce(new Error('offline'))
    await refresh()
    expect(fake.instances[0]!.destroy).toHaveBeenCalledOnce()
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeDefined()
    await refresh()
    expect(wrapper!.get('.order-pay-button').attributes('disabled')).toBeUndefined()
  })
})

describe('payment return recovery', () => {
  it('validates accessible Order before Attempt, polls matching hint and cleans provider query', async () => {
    await open('?paymentReturn=1&paymentAttemptId=P1&payment_intent=pi_x&payment_intent_client_secret=never_read&redirect_status=succeeded')
    await flushPromises()
    expect(ticketApi.getOrder).toHaveBeenCalledWith('O1')
    expect(vi.mocked(ticketApi.getOrder).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(ticketApi.getPaymentAttempt).mock.invocationCallOrder[0]!)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledWith('P1')
    expect(testRouter.currentRoute.value.fullPath).toBe('/orders/O1')
    expect(wrapper!.text()).not.toContain('never_read')
    expect(ticketApi.payOrder).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(vi.mocked(ticketApi.getPaymentAttempt).mock.calls.length).toBeGreaterThan(1)
  })
  it('terminal Attempt refreshes Order and notifications without polling', async () => {
    attempt.status = 'SUCCEEDED'
    const notification = vi.fn()
    window.addEventListener('ticketing:refresh-notifications', notification)
    try {
      await open('?paymentReturn=1&paymentAttemptId=P1')
      expect(ticketApi.getOrder).toHaveBeenCalledTimes(2)
      expect(notification).toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(2000)
      expect(ticketApi.getPaymentAttempt).toHaveBeenCalledOnce()
    } finally { window.removeEventListener('ticketing:refresh-notifications', notification) }
  })
  it('mismatched order never starts polling', async () => {
    attempt.orderId = 'O2'
    await open('?paymentReturn=1&paymentAttemptId=P1')
    await vi.advanceTimersByTimeAsync(2000)
    expect(ticketApi.getPaymentAttempt).toHaveBeenCalledOnce()
    expect(wrapper!.text()).toContain('与当前订单不匹配')
    expect(testRouter.currentRoute.value.fullPath).toBe('/orders/O1')
  })
  it.each(['', '&paymentAttemptId=', '&paymentAttemptId=P1&paymentAttemptId=P2'])('invalid hint %s remains safe', async (hint) => {
    await open('?paymentReturn=1' + hint)
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('支付恢复信息无效')
    expect(testRouter.currentRoute.value.fullPath).toBe('/orders/O1')
  })
  it('inaccessible Attempt does not break the page or reveal raw errors', async () => {
    vi.mocked(ticketApi.getPaymentAttempt).mockRejectedValue(new Error(secret))
    await open('?paymentReturn=1&paymentAttemptId=missing')
    expect(wrapper!.text()).toContain('无法恢复该支付尝试')
    expect(wrapper!.text()).toContain('待支付')
    expect(wrapper!.text()).not.toContain(secret)
    expect(testRouter.currentRoute.value.fullPath).toBe('/orders/O1')
  })
  it('inaccessible Order prevents reading the hint', async () => {
    vi.mocked(ticketApi.getOrder).mockRejectedValue(new Error('404'))
    await open('?paymentReturn=1&paymentAttemptId=P1')
    expect(ticketApi.getPaymentAttempt).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('订单不存在或不可访问')
    expect(testRouter.currentRoute.value.fullPath).toBe('/orders/O1')
  })
})
