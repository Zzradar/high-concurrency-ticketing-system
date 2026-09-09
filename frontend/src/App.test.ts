import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { authState } from './auth/authState'
import { resetMockData, setMockLatency, ticketApi, TicketApiError } from './api/ticketApi'
import { routeNames } from './navigation'
import { router } from './router'

enableAutoUnmount(afterEach)

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
    expect(wrapper.find('[aria-label="账户菜单"]').exists()).toBe(false)
    expect(wrapper.find('.progress-nav').text()).not.toContain('我的订单')
    await ticketApi.login('demo', 'Ticketing123!')
    await authState.refreshMe()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Demo 用户')
    expect(wrapper.text()).toContain('我的订单')
    wrapper.unmount()
  })

  it('opens account details without logout, navigates to orders and explicitly logs out', async () => {
    await authState.login('demo', 'Ticketing123!')
    const logout = vi.spyOn(authState, 'logout')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await flushPromises()
    const trigger = wrapper.get('[aria-label="账户菜单"]')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.account-panel').text()).toContain('Demo 用户')
    expect(wrapper.get('.account-panel').text()).toContain('demo')
    expect(logout).not.toHaveBeenCalled()
    expect(router.currentRoute.value.name).toBe(routeNames.events)
    await wrapper.get('.account-panel a').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe(routeNames.orders)
    expect(wrapper.find('.account-panel').exists()).toBe(false)
    await trigger.trigger('click')
    await wrapper.get('.account-panel button').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe(routeNames.login))
    expect(logout).toHaveBeenCalledOnce()
    expect(wrapper.find('.account-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('closes the account on notification, Escape, outside click and route change and removes listeners', async () => {
    await authState.login('demo', 'Ticketing123!')
    const add = vi.spyOn(document, 'addEventListener')
    const remove = vi.spyOn(document, 'removeEventListener')
    const wrapper = mount(App, { attachTo: document.body, global: { plugins: [router] } })
    await flushPromises()
    const account = wrapper.get('[aria-label="账户菜单"]')
    const bell = wrapper.get('[aria-label="通知中心"]')
    await bell.trigger('click')
    await account.trigger('click')
    expect(wrapper.find('.notification-panel').exists()).toBe(false)
    await bell.trigger('click')
    expect(wrapper.find('.account-panel').exists()).toBe(false)
    await account.trigger('click')
    await wrapper.get('.account-panel a').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.account-panel').exists()).toBe(false)
    expect(document.activeElement).toBe(account.element)
    await account.trigger('click')
    await wrapper.get('.account-panel header').trigger('click')
    expect(wrapper.find('.account-panel').exists()).toBe(true)
    document.body.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.account-panel').exists()).toBe(false)
    await account.trigger('click')
    await router.push('/events/evt-concert-2026/sessions')
    expect(wrapper.find('.account-panel').exists()).toBe(false)
    const listeners = add.mock.calls.filter(([event]) => ['click', 'keydown'].includes(event))
    wrapper.unmount()
    expect(listeners).toHaveLength(2)
    for (const [event, listener] of listeners) expect(remove).toHaveBeenCalledWith(event, listener)
  })

  it.each([
    ['/events', '活动'],
    ['/events/evt-concert-2026/sessions', '活动'],
    ['/sessions/ses-concert-1001/seats', '活动'],
    ['/orders', '我的订单'],
    ['/orders/missing-order', '我的订单'],
  ])('keeps the business navigation active on %s', async (path, section) => {
    await authState.login('demo', 'Ticketing123!')
    await router.push(path)
    const wrapper = mount(App, { global: { plugins: [router], stubs: { RouterView: true } } })
    expect(wrapper.findAll('.progress-nav .is-active')).toHaveLength(1)
    expect(wrapper.get('.progress-nav .is-active').text()).toBe(section)
    expect(wrapper.get('.progress-nav .is-active').attributes('aria-current')).toBe('page')
    await flushPromises()
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

    const callsBeforeRefresh = getSeatAvailability.mock.calls.length
    await wrapper.get('button[aria-label="刷新座位状态"]').trigger('click')
    await flushPromises()

    expect(getSeatAvailability).toHaveBeenCalledTimes(callsBeforeRefresh + 1)
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

  it.each([false, true])('refreshes exactly once after first checkout conflict (refresh fails: %s)', async (fails) => {
    await authState.login('demo', 'Ticketing123!')
    await router.push('/sessions/ses-concert-1001/seats')
    const layout = vi.spyOn(ticketApi, 'getSeatLayout')
    const availability = vi.spyOn(ticketApi, 'getSeatAvailability')
    const legacy = vi.spyOn(ticketApi, 'getSeats')
    vi.spyOn(ticketApi, 'createCheckoutSession').mockRejectedValueOnce(new TicketApiError('conflict', 'SEAT_TEMPORARILY_HELD'))
    const wrapper = mount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(wrapper.find('button[aria-label="A01，可选，¥1,280"]').exists()).toBe(true))
    const snapshot = await availability.mock.results[0]!.value
    const targetId = wrapper.findComponent({ name: 'SeatSelectionView' }).props('seats').find((seat: { label: string }) => seat.label === 'A01').id
    if (fails) availability.mockRejectedValueOnce(new Error('offline'))
    else availability.mockResolvedValueOnce(snapshot.map((seat: { id: string; status: string }) => ({ ...seat, status: seat.id === targetId ? 'HELD' : seat.status })))
    const before = availability.mock.calls.length
    await wrapper.get('button[aria-label="A01，可选，¥1,280"]').trigger('click')
    await flushPromises()
    expect(availability).toHaveBeenCalledTimes(before + 1)
    expect(availability).toHaveBeenLastCalledWith('ses-concert-1001', undefined)
    expect(layout).toHaveBeenCalledOnce()
    expect(legacy).not.toHaveBeenCalled()
    expect(wrapper.findAll('.selected-seat')).toHaveLength(0)
    if (fails) {
      expect(wrapper.find('button[aria-label="A01，可选，¥1,280"]').exists()).toBe(true)
      expect(wrapper.get('.availability-warning').text()).toContain('已保留当前座位图')
      expect(wrapper.get('[role="alert"]').text()).toContain('最新座位状态暂未取得')
      expect(wrapper.get('[role="alert"]').text()).not.toContain('已刷新')
    } else {
      expect(wrapper.get('button[aria-label="A01，锁定中，¥1,280"]').attributes('disabled')).toBeDefined()
      expect(wrapper.get('[role="alert"]').text()).toContain('已刷新，请重新选择')
    }
    wrapper.unmount()
  })

  it('does not poll seat availability and manual refresh makes exactly one contextual request', async () => {
    await authState.login('demo', 'Ticketing123!')
    await router.push('/sessions/ses-concert-1001/seats')
    const availability = vi.spyOn(ticketApi, 'getSeatAvailability')
    const layout = vi.spyOn(ticketApi, 'getSeatLayout')
    const legacy = vi.spyOn(ticketApi, 'getSeats')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(wrapper.find('button[aria-label="A01，可选，¥1,280"]').exists()).toBe(true))
    await wrapper.get('button[aria-label="A01，可选，¥1,280"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.selected-seat').exists()).toBe(true))
    await vi.waitFor(() => expect(wrapper.get('button[aria-label="A02，可选，¥1,280"]').attributes('disabled')).toBeUndefined())
    const before = availability.mock.calls.length
    const checkoutId = availability.mock.calls.at(-1)![1]
    expect(checkoutId).toEqual(expect.any(String))
    vi.useFakeTimers()
    try {
      await vi.advanceTimersByTimeAsync(16_000)
      expect(availability).toHaveBeenCalledTimes(before)
    } finally {
      vi.useRealTimers()
    }
    await wrapper.get('button[aria-label="刷新座位状态"]').trigger('click')
    await flushPromises()
    expect(availability).toHaveBeenCalledTimes(before + 1)
    expect(availability).toHaveBeenLastCalledWith('ses-concert-1001', checkoutId)
    expect(layout).toHaveBeenCalledOnce()
    expect(legacy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    [false, false, 'SEAT_TEMPORARILY_HELD'],
    [true, false, 'SEAT_TEMPORARILY_HELD'],
    [false, true, 'SEAT_TEMPORARILY_HELD'],
    [true, true, 'SEAT_TEMPORARILY_HELD'],
    [false, false, 'SERVICE_UNAVAILABLE'],
  ])('recovers existing checkout without duplicate refresh (%s, %s, %s)', async (recoveryFails, refreshFails, code) => {
    await authState.login('demo', 'Ticketing123!')
    await router.push('/sessions/ses-concert-1001/seats')
    const availability = vi.spyOn(ticketApi, 'getSeatAvailability')
    const layout = vi.spyOn(ticketApi, 'getSeatLayout')
    const legacy = vi.spyOn(ticketApi, 'getSeats')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(wrapper.find('button[aria-label="A01，可选，¥1,280"]').exists()).toBe(true))
    await wrapper.get('button[aria-label="A01，可选，¥1,280"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.selected-seat').exists()).toBe(true))
    await vi.waitFor(() => expect(wrapper.get('button[aria-label="A02，可选，¥1,280"]').attributes('disabled')).toBeUndefined())
    const before = availability.mock.calls.length
    const checkoutId = availability.mock.calls.at(-1)![1]
    const oldMap = wrapper.findAll('.seat-item').map((seat) => seat.attributes('aria-label'))
    vi.spyOn(ticketApi, 'replaceCheckoutSessionSeats').mockRejectedValueOnce(new TicketApiError('同步暂不可用', code))
    if (recoveryFails) vi.spyOn(ticketApi, 'getCheckoutSession').mockRejectedValueOnce(new Error('offline'))
    if (refreshFails) availability.mockRejectedValueOnce(new Error('offline'))
    await wrapper.get('button[aria-label="A02，可选，¥1,280"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('button[aria-label="A02，可选，¥1,280"]').attributes('disabled')).toBeUndefined())
    expect(availability).toHaveBeenCalledTimes(before + 1)
    expect(availability).toHaveBeenLastCalledWith('ses-concert-1001', checkoutId)
    expect(layout).toHaveBeenCalledOnce()
    expect(legacy).not.toHaveBeenCalled()
    expect(wrapper.findAll('.selected-seat')).toHaveLength(1)
    expect(wrapper.get('.selected-seat').text()).toContain('A01')
    if (refreshFails) {
      expect(wrapper.findAll('.seat-item').map((seat) => seat.attributes('aria-label'))).toEqual(oldMap)
      expect(wrapper.find('.availability-warning').exists()).toBe(true)
      expect(wrapper.get('[role="alert"]').text()).not.toContain('已刷新')
    } else if (code === 'SEAT_TEMPORARILY_HELD') {
      expect(wrapper.get('[role="alert"]').text()).toContain('已刷新，请重新选择')
    } else {
      expect(wrapper.get('[role="alert"]').text()).toBe('同步暂不可用')
    }
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
