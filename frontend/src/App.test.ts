import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { resetMockData, setMockLatency, ticketApi } from './api/ticketApi'

async function settle(milliseconds = 10) {
  await vi.advanceTimersByTimeAsync(milliseconds)
  await flushPromises()
}

async function openSeatSelection(wrapper: VueWrapper) {
  await settle()
  await wrapper.findAll('.text-button')[0]!.trigger('click')
  await settle()
  await wrapper.findAll('.session-card .primary-button')[0]!.trigger('click')
  await settle()
}

async function createPendingOrder(wrapper: VueWrapper) {
  await openSeatSelection(wrapper)
  const availableSeat = wrapper.find('button[aria-label^="A01，可选"]')
  expect(availableSeat.exists()).toBe(true)
  await availableSeat.trigger('click')

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
    await settle(20)

    expect(wrapper.text()).toContain('支付成功')
    wrapper.unmount()
  })

  it('keeps the seat conflict message after refreshing seats', async () => {
    const wrapper = mount(App)
    await openSeatSelection(wrapper)
    await wrapper.find('button[aria-label^="A01，可选"]').trigger('click')

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
})
