import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { authState } from './auth/authState'
import { resetMockData, setMockLatency, ticketApi, TicketApiError } from './api/ticketApi'
import { routeNames } from './navigation'
import { router } from './router'

describe('Phase 9 application shell and routes', () => {
  beforeEach(async () => {
    resetMockData()
    setMockLatency(0)
    authState.clearAuth()
    await router.push('/events')
    await router.isReady()
  })

  afterEach(() => {
    vi.restoreAllMocks()
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
    expect(routes.find((route) => route.path === '/orders')?.name).toBe(routeNames.orders)
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

  it('keeps a missing resource URL visible with an explicit error state', async () => {
    await router.push({ name: routeNames.eventSessions, params: { eventId: 'missing-event' } })
    const wrapper = mount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('无法打开该活动')
    })

    expect(router.currentRoute.value.fullPath).toBe('/events/missing-event/sessions')
    expect(wrapper.text()).toContain('活动不存在')
    wrapper.unmount()
  })

  it('loads the seat page from layout and availability without the legacy seat map', async () => {
    await authState.login('demo', 'Ticketing123!')
    await router.push({ name: routeNames.sessionSeats, params: { sessionId: 'ses-concert-1001' } })
    const getSeatLayout = vi.spyOn(ticketApi, 'getSeatLayout')
    const getSeatAvailability = vi.spyOn(ticketApi, 'getSeatAvailability')
    const getSeats = vi.spyOn(ticketApi, 'getSeats')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => {
      expect(wrapper.find('button[aria-label="刷新座位状态"]').exists()).toBe(true)
    })

    expect(getSeatLayout).toHaveBeenCalledOnce()
    expect(getSeatLayout).toHaveBeenCalledWith('ses-concert-1001')
    expect(getSeatAvailability).toHaveBeenCalledOnce()
    expect(getSeatAvailability).toHaveBeenCalledWith('ses-concert-1001')
    expect(getSeats).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps the current seat snapshot and selection when availability refresh fails', async () => {
    await authState.login('demo', 'Ticketing123!')
    await router.push({ name: routeNames.sessionSeats, params: { sessionId: 'ses-concert-1001' } })
    const getSeatLayout = vi.spyOn(ticketApi, 'getSeatLayout')
    const getSeatAvailability = vi.spyOn(ticketApi, 'getSeatAvailability')
    const getSeats = vi.spyOn(ticketApi, 'getSeats')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => {
      expect(wrapper.find('button[aria-label="A01，可选，¥1,280"]').exists()).toBe(true)
    })
    await wrapper.get('button[aria-label="A01，可选，¥1,280"]').trigger('click')
    await vi.waitFor(() => {
      expect(wrapper.find('button[aria-label="移除座位 A01"]').exists()).toBe(true)
    })

    const countBeforeRefresh = wrapper.findAll('.seat-item').length
    const checkoutAvailabilityCall = getSeatAvailability.mock.calls.find(
      ([, checkoutSessionId]) => typeof checkoutSessionId === 'string',
    )
    expect(checkoutAvailabilityCall).toBeDefined()
    getSeatAvailability.mockRejectedValueOnce(
      new TicketApiError('availability unavailable', 'SERVICE_UNAVAILABLE'),
    )

    await wrapper.get('button[aria-label="刷新座位状态"]').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.seat-item')).toHaveLength(countBeforeRefresh)
    expect(wrapper.find('button[aria-label="移除座位 A01"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('已保留当前座位图')
    expect(getSeatLayout).toHaveBeenCalledOnce()
    expect(getSeats).not.toHaveBeenCalled()
    expect(getSeatAvailability).toHaveBeenLastCalledWith(
      'ses-concert-1001',
      checkoutAvailabilityCall![1],
    )
    wrapper.unmount()
  })

  it.each([
    ['layout', 'getSeatLayout'],
    ['initial availability', 'getSeatAvailability'],
  ] as const)('shows a page error when %s loading fails', async (_label, method) => {
    await router.push({ name: routeNames.sessionSeats, params: { sessionId: 'ses-concert-1001' } })
    vi.spyOn(ticketApi, method).mockRejectedValueOnce(
      new TicketApiError('seat map unavailable', 'SERVICE_UNAVAILABLE'),
    )
    const wrapper = mount(App, { global: { plugins: [router] } })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('无法打开选座页')
    })
    expect(wrapper.text()).toContain('座位图加载失败，请稍后重试。')
    expect(wrapper.text()).not.toContain('当前场次暂无座位信息')
    wrapper.unmount()
  })

  it('distinguishes a successful empty layout from a seat map loading error', async () => {
    await router.push({ name: routeNames.sessionSeats, params: { sessionId: 'ses-concert-1001' } })
    vi.spyOn(ticketApi, 'getSeatLayout').mockResolvedValueOnce([])
    vi.spyOn(ticketApi, 'getSeatAvailability').mockResolvedValueOnce([])
    const wrapper = mount(App, { global: { plugins: [router] } })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('当前场次暂无座位信息')
    })
    expect(wrapper.text()).not.toContain('无法打开选座页')
    wrapper.unmount()
  })
})
