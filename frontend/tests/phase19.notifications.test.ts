import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Ref } from 'vue'
import App from '../src/App.vue'
import { authState } from '../src/auth/authState'
import { ticketApi, TicketApiError } from '../src/api/ticketApi'
import type { CurrentUser, UserNotification } from '../src/types'

vi.mock('../src/auth/authState', async () => {
  const { ref } = await import('vue')
  const currentUser = ref(null)
  return { authState: { currentUser, refreshMe: vi.fn(async () => currentUser.value),
    logout: vi.fn(async () => { currentUser.value = null; return { confirmed: true } }) } }
})
const user = authState.currentUser as Ref<CurrentUser | null>
const customer = (id: string): CurrentUser => ({ id, username: id, displayName: id, role: 'CUSTOMER' })
const note: UserNotification = { id: 'notice-1', orderId: 'order-1', type: 'PAYMENT_SUCCEEDED', title: 'old account notice', message: '', createdAt: '2026-01-01T00:00:00Z' }
let wrapper: VueWrapper | undefined
let hidden = false
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
async function open() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/events', name: 'events', component: { template: '<p>Events</p>' } },
    { path: '/login', name: 'login', component: { template: '<p>Login</p>' } },
    { path: '/orders', name: 'orders', component: { template: '<p>Orders</p>' } },
  ] })
  await router.push('/events')
  wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
}
async function visibility(value: boolean) {
  hidden = value
  document.dispatchEvent(new Event('visibilitychange'))
  await flushPromises()
}
beforeEach(() => {
  vi.useFakeTimers(); vi.spyOn(Math, 'random').mockReturnValue(.5)
  hidden = false; user.value = null
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => hidden ? 'hidden' : 'visible')
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  vi.spyOn(ticketApi, 'getNotifications').mockResolvedValue([])
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.useRealTimers() })

describe('Phase19 notification lifecycle contract', () => {
  it('does not poll anonymous users; login and bootstrap produce one immediate read', async () => {
    await open(); await vi.advanceTimersByTimeAsync(60000)
    expect(ticketApi.getNotifications).not.toHaveBeenCalled()
    user.value = customer('A'); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(29999)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
  })
  it('coalesces mounted authentication, then uses stable fields to back off unchanged arrays', async () => {
    user.value = customer('A'); vi.mocked(ticketApi.getNotifications).mockImplementation(async () => [{ ...note }])
    await open(); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30000); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(30000); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(59999); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(4)
  })
  it('merges panel, explicit signal and timer while a read is pending', async () => {
    user.value = customer('A'); await open()
    const pending = deferred<UserNotification[]>()
    vi.mocked(ticketApi.getNotifications).mockReturnValueOnce(pending.promise)
    await wrapper!.get('[aria-label="通知中心"]').trigger('click'); await flushPromises()
    window.dispatchEvent(new Event('ticketing:refresh-notifications'))
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(120000)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
    pending.resolve([]); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
  })
  it.each(['visibility-first', 'focus-first'])('pauses hidden and merges one activation, %s', async order => {
    user.value = customer('A'); await open()
    await visibility(true); await vi.advanceTimersByTimeAsync(91000)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    hidden = false
    if (order === 'visibility-first') document.dispatchEvent(new Event('visibilitychange'))
    else window.dispatchEvent(new Event('focus'))
    await flushPromises()
    if (order === 'visibility-first') window.dispatchEvent(new Event('focus'))
    else document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
  })
  it('a second real tab activation inside the merge window still restores polling', async () => {
    user.value = customer('A'); await open()
    window.dispatchEvent(new Event('focus')); await flushPromises()
    const before = vi.mocked(ticketApi.getNotifications).mock.calls.length
    await visibility(true); await vi.advanceTimersByTimeAsync(100)
    await visibility(false); window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(before + 1)
    await vi.advanceTimersByTimeAsync(60000)
    expect(vi.mocked(ticketApi.getNotifications).mock.calls.length).toBeGreaterThan(before + 1)
  })
  it('serializes a new identity behind an obsolete read and discards the old response', async () => {
    const pending = deferred<UserNotification[]>()
    user.value = customer('A'); vi.mocked(ticketApi.getNotifications).mockReturnValueOnce(pending.promise)
    await open(); user.value = customer('B'); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    pending.resolve([note]); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
    await wrapper!.get('[aria-label="通知中心"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).not.toContain(note.title)
  })
  it('logout immediately invalidates pending notifications, including a slow logout POST', async () => {
    const pending = deferred<UserNotification[]>(), logout = deferred<{ confirmed: boolean }>()
    user.value = customer('A'); vi.mocked(ticketApi.getNotifications).mockReturnValueOnce(pending.promise)
    vi.mocked(authState.logout).mockReturnValueOnce(logout.promise)
    await open(); await wrapper!.get('[aria-label="账户菜单"]').trigger('click')
    await wrapper!.findAll('button').find(b => b.text() === '退出登录')!.trigger('click')
    pending.resolve([note]); await flushPromises(); await vi.advanceTimersByTimeAsync(91000)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).not.toContain(note.title)
    user.value = null; logout.resolve({ confirmed: true }); await flushPromises()
    await vi.advanceTimersByTimeAsync(60000); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
  })
  it.each([401, 429, 503])('handles %s without rejection or a retry before Retry-After', async status => {
    user.value = customer('A')
    vi.mocked(ticketApi.getNotifications).mockRejectedValueOnce(new TicketApiError('busy', 'BUSY', status, 120000))
    await open(); await vi.advanceTimersByTimeAsync(119999)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1); expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
  })
  it('drains a read from before hiding before one authoritative visible refresh', async () => {
    const pending = deferred<UserNotification[]>()
    user.value = customer('A'); vi.mocked(ticketApi.getNotifications).mockReturnValueOnce(pending.promise)
    await open(); await visibility(true); await vi.advanceTimersByTimeAsync(91000)
    await visibility(false); window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
    pending.resolve([note]); await flushPromises()
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(2)
    await wrapper!.get('[aria-label="通知中心"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).not.toContain(note.title)
  })
  it('unmount drains an old request without restarting timers', async () => {
    const pending = deferred<UserNotification[]>()
    user.value = customer('A'); vi.mocked(ticketApi.getNotifications).mockReturnValueOnce(pending.promise)
    await open(); wrapper!.unmount(); wrapper = undefined
    pending.resolve([note]); await flushPromises(); await vi.advanceTimersByTimeAsync(120000)
    expect(ticketApi.getNotifications).toHaveBeenCalledTimes(1)
  })
})
