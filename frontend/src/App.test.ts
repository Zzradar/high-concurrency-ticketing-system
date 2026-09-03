import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { authState } from './auth/authState'
import { resetMockData, setMockLatency, ticketApi } from './api/ticketApi'
import { router } from './router'

describe('Phase 9 application shell and routes', () => {
  beforeEach(async () => {
    resetMockData()
    setMockLatency(0)
    authState.clearAuth()
    await router.push('/events')
    await router.isReady()
  })

  it('registers real deep-link routes with protected order pages', () => {
    const routes = router.getRoutes()
    expect(routes.map((route) => route.path)).toEqual(
      expect.arrayContaining([
        '/login',
        '/events',
        '/events/:eventId/sessions',
        '/sessions/:sessionId/seats',
        '/orders',
        '/orders/:orderId',
      ]),
    )
    expect(routes.find((route) => route.path === '/orders')?.meta.requiresAuth).toBe(true)
  })

  it('shows login when anonymous and current user navigation after login', async () => {
    const wrapper = mount(App, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('登录')
    await ticketApi.login('demo', 'Ticketing123!')
    await authState.refreshMe()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Demo 用户')
    expect(wrapper.text()).toContain('我的订单')
    wrapper.unmount()
  })

  it('guards order deep links and preserves the intended redirect', async () => {
    await router.push('/orders/TKT-DEEP-LINK')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/orders/TKT-DEEP-LINK')

    await authState.login('demo', 'Ticketing123!')
    await router.push('/orders/TKT-DEEP-LINK')
    expect(router.currentRoute.value.fullPath).toBe('/orders/TKT-DEEP-LINK')
  })

  it('refreshes account notifications on focus', async () => {
    await authState.login('demo', 'Ticketing123!')
    const getNotifications = vi.spyOn(ticketApi, 'getNotifications')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await flushPromises()
    const callsBeforeFocus = getNotifications.mock.calls.length
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(getNotifications.mock.calls.length).toBeGreaterThan(callsBeforeFocus)
    wrapper.unmount()
    getNotifications.mockRestore()
  })
})
