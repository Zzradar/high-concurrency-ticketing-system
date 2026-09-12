import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import SessionCard from './SessionCard.vue'
import { ticketApi } from '../api/ticketApi'
import type { TicketSession } from '../types'
let wrapper: ReturnType<typeof mount>
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); vi.restoreAllMocks() })
it('calibrates a skewed client clock and waits for server OPEN before enabling', async () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2030-01-01Z'))
  const session: TicketSession={id:'s',eventId:'e',date:'10月1日',time:'19:00',weekday:'周四',venue:'场馆',gateTime:'17:00',status:'ON_SALE',priceFrom:100,availability:'充足',salesWindow:{startsAt:'2026-09-01T00:00:05Z',endsAt:'2026-09-01T00:01:00Z',evaluatedAt:'2026-09-01T00:00:00Z',state:'NOT_STARTED'}}
  let finish!: (s:TicketSession)=>void
  const get=vi.spyOn(ticketApi,'getSession').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  wrapper=mount(SessionCard,{props:{session}})
  expect(wrapper.text()).toContain('距开售 5 秒');expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  await vi.advanceTimersByTimeAsync(6000);expect(get).toHaveBeenCalledOnce()
  expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  finish({...session,salesWindow:{...session.salesWindow,state:'OPEN',evaluatedAt:'2026-09-01T00:00:06Z'}})
  await vi.advanceTimersByTimeAsync(1);expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
  await wrapper.setProps({eventAvailable:false});expect(wrapper.find('button').attributes('disabled')).toBeDefined()
})
