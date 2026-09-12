import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App.vue'
import { authState } from '../auth/authState'
import { resetMockData, setMockLatency, ticketApi } from '../api/ticketApi'
import { router } from '../router'
import type { SeatAvailabilitySyncResponse } from '../types'

let wrapper: ReturnType<typeof mount>
beforeEach(async () => {
  resetMockData();setMockLatency(0);authState.clearAuth()
  await router.push('/sessions/ses-concert-1001/seats');await router.isReady()
  vi.useFakeTimers();vi.spyOn(document,'hidden','get').mockReturnValue(false)
})
afterEach(() => {wrapper?.unmount();vi.useRealTimers();vi.restoreAllMocks()})
async function open() {
  const spy=vi.spyOn(ticketApi,'getSeatAvailability')
  wrapper=mount(App,{global:{plugins:[router]}})
  await vi.advanceTimersByTimeAsync(100)
  expect(wrapper.find('.seat-grid').exists()).toBe(true)
  return spy
}
describe('Phase16 page synchronization', () => {
  it('loads one real Zone then polls Delta, pauses hidden and resumes visible', async () => {
    const spy=await open()
    expect(spy).toHaveBeenCalledOnce()
    expect(spy.mock.calls[0]![2]).toEqual({zone:expect.any(String)})
    await vi.advanceTimersByTimeAsync(2100)
    expect(spy.mock.calls[1]![2]).toEqual({zone:expect.any(String),generation:expect.any(String),since:expect.any(String)})
    const hidden=vi.spyOn(document,'hidden','get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    const before=spy.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(spy).toHaveBeenCalledTimes(before)
    hidden.mockReturnValue(false);document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(20)
    expect(spy).toHaveBeenCalledTimes(before+1)
  })
  it('requests a fresh Snapshot immediately when authentication changes', async () => {
    const spy=await open()
    await vi.advanceTimersByTimeAsync(2100)
    expect(spy.mock.calls.at(-1)![2]?.since).toBeDefined()
    vi.spyOn(ticketApi,'me').mockResolvedValue({id:'phase16-auth-change',displayName:'Reader',username:'reader'})
    const refresh=authState.refreshMe();await vi.advanceTimersByTimeAsync(20);await refresh
    expect(spy.mock.calls.at(-1)![2]).toEqual({zone:expect.any(String)})
  })
  it('immediately drains hasMore and advances only to each returned cursor', async () => {
    const spy=await open()
    const first=await spy.mock.results[0]!.value as SeatAvailabilitySyncResponse
    spy.mockResolvedValueOnce({...first,mode:'delta',changes:[],cursor:'2-0',hasMore:true})
    spy.mockResolvedValueOnce({...first,mode:'delta',changes:[],cursor:'3-0',hasMore:false})
    await vi.advanceTimersByTimeAsync(2100)
    expect(spy).toHaveBeenCalledTimes(3)
    expect(spy.mock.calls[2]![2]?.since).toBe('2-0')
  })
  it('uses slow retries for degraded snapshots and returns to Snapshot without cursor', async () => {
    const spy=await open()
    const first=await spy.mock.results[0]!.value as SeatAvailabilitySyncResponse
    if(first.mode!=='snapshot')throw new Error('snapshot')
    spy.mockResolvedValueOnce({...first,degraded:true,reset:true,generation:null,cursor:null})
    await vi.advanceTimersByTimeAsync(2100)
    const before=spy.mock.calls.length
    await vi.advanceTimersByTimeAsync(3000);expect(spy).toHaveBeenCalledTimes(before)
    await vi.advanceTimersByTimeAsync(2100);expect(spy).toHaveBeenCalledTimes(before+1)
    expect(spy.mock.calls.at(-1)![2]).toEqual({zone:first.zone})
  })
  it('fences a delayed response after switching Zones', async () => {
    const spy=await open()
    const first=await spy.mock.results[0]!.value as SeatAvailabilitySyncResponse
    if(first.mode!=='snapshot')throw new Error('snapshot')
    let finish!: (value: SeatAvailabilitySyncResponse)=>void
    spy.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
    await wrapper.get('button[aria-label="刷新座位状态"]').trigger('click')
    await flushPromises()
    const zones=wrapper.findAll('.zone-browser button')
    await zones[1]!.trigger('click');await vi.advanceTimersByTimeAsync(20)
    const heading=wrapper.get('.seat-map-panel__heading').text()
    finish({...first,seats:first.seats.map(s=>({...s,status:'SOLD'}))})
    await flushPromises()
    expect(wrapper.get('.seat-map-panel__heading').text()).toBe(heading)
    expect(heading).not.toContain(first.zone)
  })
  it('serializes repeated focus requests and stops timers after unmount', async () => {
    const spy=await open()
    const first=await spy.mock.results[0]!.value as SeatAvailabilitySyncResponse
    let finish!: (value: SeatAvailabilitySyncResponse)=>void
    spy.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
    window.dispatchEvent(new Event('focus'));window.dispatchEvent(new Event('focus'))
    await flushPromises();expect(spy).toHaveBeenCalledTimes(2)
    finish(first);await vi.advanceTimersByTimeAsync(20)
    wrapper.unmount();const before=spy.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000);expect(spy).toHaveBeenCalledTimes(before)
  })
})
