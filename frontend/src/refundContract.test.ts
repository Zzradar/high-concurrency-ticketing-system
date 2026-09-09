import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from './App.vue'
import { ticketApi } from './api/ticketApi'
import { authState } from './auth/authState'
import { orderFixture, refundFixture, summaryFixture } from './test/refundFixtures'
import type { BuyerRefundSummary, NotificationType, RefundEligibility, TicketOrder, UserNotification } from './types'

afterEach(() => { vi.restoreAllMocks(); authState.clearAuth() })

describe('Phase 12 public types and notifications', () => {
  it('keeps required nullable summary, optional eligibility, and resource-only terminal fields distinct', () => {
    const listOrder: TicketOrder = { ...orderFixture }
    delete listOrder.refundEligibility
    expect(listOrder.buyerRefund).toBeNull()
    expect(listOrder.refundEligibility).toBeUndefined()
    expect(Object.keys(summaryFixture)).not.toContain('createdAt')
    expect(refundFixture.createdAt).toBe('2026-09-09T02:00:00.000Z')
    // Compile-time checks are also run by vue-tsc; no nullable fields are papered over.
    const { buyerRefund, ...withoutSummary } = orderFixture
    // @ts-expect-error buyerRefund is required in every backend TicketOrder JSON
    const missing: TicketOrder = withoutSummary
    // @ts-expect-error omitted eligibility is supported, explicit null is not emitted
    const nullEligibility: RefundEligibility = null
    // @ts-expect-error SYSTEM is not a buyer summary
    const system: BuyerRefundSummary = { ...summaryFixture, source: 'SYSTEM' }
    void buyerRefund; void missing; void nullEligibility; void system
  })

  it('renders all four refund notifications and navigates to their local order', async () => {
    const types: NotificationType[] = ['AUTO_REFUND_COMPLETED', 'AUTO_REFUND_FAILED', 'REFUND_COMPLETED', 'REFUND_FAILED']
    const items: UserNotification[] = types.map((type, index) => ({ id: 'N' + index, orderId: 'O1', type, title: type, message: '退款状态通知 ' + index, createdAt: '2026-09-09T02:00:00.000Z' }))
    const user = { id: 'test-user', username: 'test', displayName: '测试账户' }
    vi.spyOn(ticketApi, 'me').mockResolvedValue(user)
    vi.spyOn(ticketApi, 'getNotifications').mockResolvedValue(items)
    vi.spyOn(ticketApi, 'markNotificationRead').mockImplementation(async (id) => {
      const notification = items.find((item) => item.id === id)
      if (!notification) throw new Error('missing fixture')
      return { ...notification, readAt: '2026-09-09T02:01:00.000Z' }
    })
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/events', name: 'events', component: { template: '<div />' } },
      { path: '/orders', name: 'orders', component: { template: '<div />' } },
      { path: '/orders/:orderId', name: 'order-detail', component: { template: '<div />' } },
      { path: '/login', name: 'login', component: { template: '<div />' } },
    ] })
    await router.push('/events')
    const wrapper = mount(App, { global: { plugins: [router] } })
    try {
      await flushPromises()
      await wrapper.get('button[aria-label="通知中心"]').trigger('click')
      expect(wrapper.findAll('.notification-item')).toHaveLength(4)
      for (const type of types) expect(wrapper.get('.notification-panel').text()).toContain(type)
      await wrapper.get('.notification-item').trigger('click'); await flushPromises()
      expect(ticketApi.markNotificationRead).toHaveBeenCalledWith('N0')
      expect(router.currentRoute.value.path).toBe('/orders/O1')
    } finally { wrapper.unmount() }
  })
})
