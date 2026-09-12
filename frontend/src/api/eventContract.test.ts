import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import EventCard from '../components/EventCard.vue'
import type { TicketEvent } from '../types'
const valid = {admission:{required:false,state:'NOT_REQUIRED',prequeueStartsAt:null},id:'e',name:'N',description:'',city:'C',venue:'V',dateRange:'D',cover:'',category:'C',status:'ON_SALE',sessionCount:1,
 salesWindow:{startsAt:'2026-01-01T00:00:00Z',endsAt:'2027-01-01T00:00:00Z',evaluatedAt:'2026-09-12T00:00:00Z',state:'OPEN'}}
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllEnvs();vi.resetModules()})
for (const [name, window] of Object.entries({missing:undefined,empty:{},arrayState:{...valid.salesWindow,state:['OPEN']},nestedArrayState:{...valid.salesWindow,state:[['OPEN']]},invalidDate:{...valid.salesWindow,startsAt:'garbage'},invalidCalendar:{...valid.salesWindow,startsAt:'2026-02-30T00:00:00Z'},emptyRange:{...valid.salesWindow,endsAt:valid.salesWindow.startsAt},valid:valid.salesWindow})) {
 it(`validates ${name} at both real API entry points`,async()=>{
  vi.stubEnv('MODE','development');vi.stubEnv('VITE_USE_MOCK_API','false');vi.resetModules()
  const {ticketApi,http,TicketApiError}=await import('./ticketApi')
  const event={...valid,salesWindow:window}
  vi.spyOn(http,'get').mockResolvedValueOnce({data:[event]}).mockResolvedValueOnce({data:event})
  if(name==='valid') {expect(await ticketApi.getEvents()).toEqual([event]);expect(await ticketApi.getEvent('e')).toEqual(event)}
  else {await expect(ticketApi.getEvents()).rejects.toBeInstanceOf(TicketApiError);await expect(ticketApi.getEvent('e')).rejects.toMatchObject({code:'INVALID_EVENT_RESPONSE'})}
 })
 it(`renders ${name} safely without invented sale dates`,()=>{
  const wrapper=mount(EventCard,{props:{event:{...valid,salesWindow:window} as TicketEvent}})
  expect(wrapper.text()).toContain(name==='valid'?'距停售':'售票信息暂不可用')
  expect(wrapper.find('small').exists()).toBe(name==='valid')
  wrapper.unmount()
 })
}
it('rejects malformed event fields, non-array list and wrong detail identity',async()=>{
 vi.stubEnv('MODE','development');vi.stubEnv('VITE_USE_MOCK_API','false');vi.resetModules()
 const {ticketApi,http}=await import('./ticketApi')
 const get=vi.spyOn(http,'get')
 for(const data of [null,{},[{...valid,name:null}],[{...valid,sessionCount:-1}],[{...valid,status:'DRAFT'}]]){
  get.mockResolvedValueOnce({data});await expect(ticketApi.getEvents()).rejects.toMatchObject({code:'INVALID_EVENT_RESPONSE'})
 }
 get.mockResolvedValueOnce({data:valid});await expect(ticketApi.getEvent('wrong')).rejects.toMatchObject({code:'INVALID_EVENT_RESPONSE'})
})

it('rejects non-string enums at both API entry points', async () => {
  vi.stubEnv('MODE', 'development')
  vi.stubEnv('VITE_USE_MOCK_API', 'false')
  vi.resetModules()
  const { ticketApi, http } = await import('./ticketApi')
  const get = vi.spyOn(http, 'get')
  for (const value of [undefined, null, true, 1, {}, [], ['OPEN'], [['OPEN']], ['ON_SALE'], [['ON_SALE']]]) {
    for (const event of [
      { ...valid, salesWindow: { ...valid.salesWindow, state: value } },
      { ...valid, status: value },
    ]) {
      get.mockResolvedValueOnce({ data: [event] }).mockResolvedValueOnce({ data: event })
      await expect(ticketApi.getEvents()).rejects.toMatchObject({ code: 'INVALID_EVENT_RESPONSE' })
      await expect(ticketApi.getEvent('e')).rejects.toMatchObject({ code: 'INVALID_EVENT_RESPONSE' })
    }
  }
})

it('accepts only the declared string enum values without coercion', async () => {
  const { isSalesWindow, isTicketEvent } = await import('../utils/eventContract')
  for (const state of ['NOT_STARTED', 'OPEN', 'ENDED']) {
    expect(isSalesWindow({ ...valid.salesWindow, state })).toBe(true)
  }
  for (const status of ['ON_SALE', 'COMING_SOON']) {
    expect(isTicketEvent({ ...valid, status })).toBe(true)
  }
  const coercible = { toString: () => 'OPEN' }
  expect(isSalesWindow({ ...valid.salesWindow, state: coercible })).toBe(false)
  expect(isTicketEvent({ ...valid, status: { toString: () => 'ON_SALE' } })).toBe(false)
  for (const state of ['', 'open', ' OPEN ', 'UNKNOWN']) {
    expect(isSalesWindow({ ...valid.salesWindow, state })).toBe(false)
  }
})