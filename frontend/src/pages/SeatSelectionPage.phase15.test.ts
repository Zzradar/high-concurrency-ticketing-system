import { mount } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import App from '../App.vue'
import { authState, checkoutLocatorKey } from '../auth/authState'
import { resetMockData, setMockLatency, setMockSalesClock, setMockSalesWindow, ticketApi, TicketApiError } from '../api/ticketApi'
import { router } from '../router'
let wrapper: ReturnType<typeof mount>
const id = 'ses-concert-1001', start = Date.parse('2026-09-12T00:00:00Z'), end = start + 5000
beforeEach(async () => {
  resetMockData(); setMockLatency(0); authState.clearAuth(); sessionStorage.clear()
  await router.push('/sessions/'+id+'/seats'); await router.isReady()
  vi.useFakeTimers(); vi.setSystemTime(start)
  vi.spyOn(document,'hidden','get').mockReturnValue(false)
  setMockSalesWindow('evt-concert-2026',new Date(start).toISOString(),new Date(end).toISOString())
})
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); vi.restoreAllMocks() })
async function open(now: number) {
  setMockSalesClock(now)
  const availability = vi.spyOn(ticketApi,'getSeatAvailability')
  const session = vi.spyOn(ticketApi,'getSession')
  wrapper = mount(App,{global:{plugins:[router]}})
  await vi.advanceTimersByTimeAsync(100)
  expect(wrapper.find('.seat-grid').exists()).toBe(true)
  return {availability,session}
}
it.each([start-10000,end])('loads one Snapshot and keeps closed page quiet at %s', async now => {
  const spies = await open(now)
  expect(spies.availability).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(8000)
  expect(spies.availability).toHaveBeenCalledOnce()
  expect(wrapper.findAll('.seat-item').every(button => button.attributes('disabled') !== undefined)).toBe(true)
})
it('checks each boundary once and starts/stops Delta only on server state', async () => {
  const spies = await open(start-1000)
  setMockSalesClock(start)
  await vi.advanceTimersByTimeAsync(1100)
  expect(spies.session).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(2100)
  expect(spies.availability.mock.calls.at(-1)?.[2]?.since).toBeDefined()
  setMockSalesClock(end)
  await vi.advanceTimersByTimeAsync(3100)
  expect(spies.session).toHaveBeenCalledTimes(3)
  const count = spies.availability.mock.calls.length
  await vi.advanceTimersByTimeAsync(10000)
  expect(spies.availability).toHaveBeenCalledTimes(count)
  expect(spies.session).toHaveBeenCalledTimes(3)
})
it('treats SALES_ENDED as deterministic, refreshes once and clears selection without recovery polling', async () => {
  setMockSalesClock(start)
  const login = authState.login('demo','Ticketing123!'); await vi.advanceTimersByTimeAsync(5); await login
  const spies = await open(start)
  const seat = wrapper.find('.seat-item--available')
  await seat.trigger('click'); await vi.advanceTimersByTimeAsync(20)
  expect(wrapper.find('.selected-seat').exists()).toBe(true)
  setMockSalesClock(end)
  vi.spyOn(ticketApi,'confirmCheckoutSession').mockRejectedValueOnce(new TicketApiError('Closed','SALES_ENDED',409))
  const get = vi.spyOn(ticketApi,'getCheckoutSession')
  const abandon = vi.spyOn(ticketApi,'abandonCheckoutSession')
  const button = wrapper.findAll('button').find(b => b.text().includes('提交预订'))!
  await button.trigger('click'); await vi.advanceTimersByTimeAsync(100)
  expect(spies.session).toHaveBeenCalledTimes(2)
  expect(get).not.toHaveBeenCalled(); expect(abandon).toHaveBeenCalledOnce()
  expect(sessionStorage.getItem(checkoutLocatorKey()!)).toBeNull()
  expect(wrapper.find('.selected-seat').exists()).toBe(false)
  expect(wrapper.find('.seat-grid').exists()).toBe(true)
  await vi.advanceTimersByTimeAsync(10000); expect(get).not.toHaveBeenCalled()
})
