import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { resetMockData, setMockLatency } from './api/ticketApi'

async function settle(milliseconds = 10) {
  await vi.advanceTimersByTimeAsync(milliseconds)
  await flushPromises()
}

describe('ticket booking demo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetMockData()
    setMockLatency(1)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('completes event, session, seat, reservation and payment flow', async () => {
    const wrapper = mount(App)
    await settle()

    expect(wrapper.text()).toContain('正在售票')
    await wrapper.findAll('.text-button')[0]!.trigger('click')
    await settle()

    expect(wrapper.text()).toContain('选择场次')
    await wrapper.findAll('.session-card .primary-button')[0]!.trigger('click')
    await settle()

    const availableSeat = wrapper.find('button[aria-label^="A01，可选"]')
    expect(availableSeat.exists()).toBe(true)
    await availableSeat.trigger('click')
    expect(wrapper.text()).toContain('A01')

    const reserveButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('提交预订'))
    expect(reserveButton).toBeDefined()
    await reserveButton!.trigger('click')
    await settle(20)

    expect(wrapper.text()).toContain('请确认并完成支付')
    expect(wrapper.text()).toContain('待支付')

    const payButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('模拟支付'))
    expect(payButton).toBeDefined()
    await payButton!.trigger('click')
    await settle(20)

    expect(wrapper.text()).toContain('支付成功')
    wrapper.unmount()
  })
})
