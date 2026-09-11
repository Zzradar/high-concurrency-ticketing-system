import { beforeEach, describe, expect, it } from 'vitest'
import { ZoneAvailabilityState } from './zoneAvailability'
import { resetMockData, setMockLatency, ticketApi } from '../api/ticketApi'
import type { SeatAvailabilitySnapshotResponse, SeatStatic } from '../types'

const layout: SeatStatic[] = ['A','B'].flatMap(zone => [1,2].map(number => ({id:zone+number,sessionId:'S',label:zone+number,row:zone,number,zone,price:100})))
const snapshot = (zone: string): SeatAvailabilitySnapshotResponse => ({
  sessionId:'S',zone,mode:'snapshot',generation:'g1',cursor:'1-0',reset:false,degraded:false,hasMore:false,
  zones:[{zone,total:2,available:2,held:0,sold:0}],seats:layout.filter(s=>s.zone===zone).map(s=>({id:s.id,status:'AVAILABLE'})),
})
describe('ZoneAvailabilityState', () => {
  it('patches a Delta while retaining other Zone statuses', () => {
    const state=new ZoneAvailabilityState(layout)
    state.apply(snapshot('A'));state.apply(snapshot('B'))
    state.apply({...snapshot('A'),mode:'delta',changes:[{id:'A1',status:'HELD'}],cursor:'2-0'})
    expect(state.statusBySeatId.get('A1')).toBe('HELD')
    expect(state.statusBySeatId.get('B1')).toBe('AVAILABLE')
    expect(state.sync.get('A')?.cursor).toBe('2-0')
  })
  it.each(['generation','trim'])('replaces the complete Zone after a %s reset', () => {
    const state=new ZoneAvailabilityState(layout);state.apply(snapshot('A'))
    state.apply({...snapshot('A'),reset:true,generation:'g2',seats:[{id:'A1',status:'SOLD'},{id:'A2',status:'HELD'}]})
    expect(state.seats().map(s=>s.status)).toEqual(['SOLD','HELD'])
    expect(state.sync.get('A')?.generation).toBe('g2')
  })
  it('rejects invalid snapshots atomically and unexpected Delta generations', () => {
    const state=new ZoneAvailabilityState(layout);state.apply(snapshot('A'))
    for(const seats of [[{id:'B1',status:'SOLD' as const}],[{id:'A1',status:'SOLD' as const}]]) {
      expect(()=>state.apply({...snapshot('A'),seats})).toThrow()
      expect(state.statusBySeatId.get('A1')).toBe('AVAILABLE')
    }
    expect(()=>state.apply({...snapshot('A'),mode:'delta',generation:'g2',changes:[]})).toThrow()
  })
  it('retains a degraded snapshot without a cursor', () => {
    const state=new ZoneAvailabilityState(layout)
    state.apply({...snapshot('A'),degraded:true,reset:true,generation:null,cursor:null})
    expect(state.sync.get('A')).toEqual({loaded:true,degraded:true,generation:null,cursor:null})
  })
})
describe('Phase16 mock Delta', () => {
  beforeEach(()=>{resetMockData();setMockLatency(0)})
  it('reports holds to anonymous, owner snapshots, and release deltas', async () => {
    await ticketApi.login('demo','Ticketing123!')
    const session='ses-concert-1001'
    const layout=await ticketApi.getSeatLayout(session)
    const zone=layout[0]!.zone
    const first=await ticketApi.getSeatAvailability(session,undefined,{zone})
    if(first.mode!=='snapshot')throw new Error('snapshot required')
    const seat=first.seats.find(s=>s.status==='AVAILABLE')!
    const checkout=await ticketApi.createCheckoutSession(session,[seat.id])
    const changed=await ticketApi.getSeatAvailability(session,undefined,{zone,generation:first.generation!,since:first.cursor!})
    expect(changed.mode).toBe('delta')
    if(changed.mode!=='delta')throw new Error('delta required')
    expect(changed.changes).toContainEqual({id:seat.id,status:'HELD'})
    const own=await ticketApi.getSeatAvailability(session,checkout.id,{zone})
    if(own.mode!=='snapshot')throw new Error('snapshot required')
    expect(own.seats).toContainEqual({id:seat.id,status:'AVAILABLE'})
    await ticketApi.abandonCheckoutSession(checkout.id)
    const released=await ticketApi.getSeatAvailability(session,undefined,{zone,generation:changed.generation!,since:changed.cursor!})
    if(released.mode!=='delta')throw new Error('delta required')
    expect(released.changes).toContainEqual({id:seat.id,status:'AVAILABLE'})
    const empty=await ticketApi.getSeatAvailability(session,undefined,{zone,generation:released.generation!,since:released.cursor!})
    expect(empty.cursor).toBe(released.cursor)
    expect(empty.mode==='delta' && empty.changes).toEqual([])
  })
})
