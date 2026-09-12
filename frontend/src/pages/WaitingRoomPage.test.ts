import { mount } from '@vue/test-utils'
import { afterEach,beforeEach,expect,it,vi } from 'vitest'
import App from '../App.vue'
import { router } from '../router'
import { routeNames } from '../navigation'
import { authState,checkoutLocatorKey } from '../auth/authState'
import { ticketApi,resetMockData,setMockLatency,TicketApiError } from '../api/ticketApi'
import { admissionApi } from '../api/admissionApi'
import type { AdmissionStatus,CheckoutSession } from '../types'
const eventId='evt-concert-2026',sessionId='ses-concert-1001'
const summary={required:true,state:'OPEN' as const,prequeueStartsAt:'2026-01-01T00:00:00Z'}
const state=(name:AdmissionStatus['state']='NOT_JOINED'):AdmissionStatus=>({state:name,queueGeneration:'a'.repeat(32),positionApprox:['WAITING','PAUSED'].includes(name)?3:null,admittedUntil:name==='ADMITTED'?'2030-01-01T00:00:00Z':null,pollAfterMs:2000,heartbeatAfterMs:['WAITING','PAUSED','ADMITTED'].includes(name)?5000:null,serverTime:new Date().toISOString(),joinAllowed:true})
let wrapper:ReturnType<typeof mount>|undefined
beforeEach(async()=>{
 resetMockData();setMockLatency(0);authState.clearAuth();sessionStorage.clear()
 vi.spyOn(ticketApi,'me').mockResolvedValue({id:'p18-reader',username:'reader',displayName:'Reader',role:'CUSTOMER'});await authState.refreshMe()
 const getEvent=ticketApi.getEvent,getSession=ticketApi.getSession
 vi.spyOn(ticketApi,'getEvent').mockImplementation(async id=>({...await getEvent(id),admission:summary}))
 vi.spyOn(ticketApi,'getSession').mockImplementation(async id=>({...await getSession(id),admission:summary}))
 vi.spyOn(ticketApi,'listRecoverableCheckoutSessions').mockResolvedValue([])
 vi.spyOn(ticketApi,'getOrders').mockResolvedValue([])
 vi.spyOn(admissionApi,'status').mockResolvedValue(state())
 vi.spyOn(admissionApi,'join').mockResolvedValue(state('WAITING'))
 vi.spyOn(admissionApi,'heartbeat').mockResolvedValue(state('ADMITTED'))
 vi.spyOn(admissionApi,'leave').mockResolvedValue(state())
 await router.push({name:routeNames.waitingRoom,params:{eventId},query:{sessionId}});await router.isReady()
 vi.useFakeTimers();vi.spyOn(Math,'random').mockReturnValue(.5);vi.spyOn(document,'hidden','get').mockReturnValue(false)
})
afterEach(()=>{wrapper?.unmount();wrapper=undefined;vi.useRealTimers();vi.restoreAllMocks()})
async function open(){wrapper=mount(App,{global:{plugins:[router]}});await vi.advanceTimersByTimeAsync(100)}
it('requires explicit join, shows approximate position, and stops waiting polls after admission',async()=>{
 await open();expect(admissionApi.join).not.toHaveBeenCalled()
 await wrapper!.findAll('button').find(b=>b.text()==='加入队列')!.trigger('click');await vi.advanceTimersByTimeAsync(20)
 expect(admissionApi.join).toHaveBeenCalledOnce();expect(wrapper!.text()).toContain('前方约 2 人')
 vi.mocked(admissionApi.status).mockResolvedValue(state('ADMITTED'))
 const availability=vi.spyOn(ticketApi,'getSeatAvailability')
 await vi.advanceTimersByTimeAsync(2100);expect(router.currentRoute.value.name).toBe(routeNames.sessionSeats)
 const statusCount=vi.mocked(admissionApi.status).mock.calls.length
 await vi.advanceTimersByTimeAsync(6100);expect(admissionApi.status).toHaveBeenCalledTimes(statusCount)
 expect(admissionApi.heartbeat).toHaveBeenCalledOnce();expect(availability.mock.calls.length).toBeGreaterThan(1)
})
it('requires explicit reset join and never automatically promotes the old generation',async()=>{
 vi.mocked(admissionApi.status).mockResolvedValue(state('RESET_REQUIRED'));await open()
 await vi.advanceTimersByTimeAsync(10000);expect(admissionApi.status).toHaveBeenCalledOnce();expect(admissionApi.join).not.toHaveBeenCalled()
 await wrapper!.findAll('button').find(b=>b.text()==='重新加入队列')!.trigger('click');await vi.advanceTimersByTimeAsync(20)
 expect(admissionApi.join).toHaveBeenCalledWith(eventId,undefined)
})
it('renders distinct 429/503 text and obeys backoff without exposing internal errors',async()=>{
 vi.mocked(admissionApi.status).mockRejectedValueOnce(new TicketApiError('internal storage error','ADMISSION_UNAVAILABLE',503,8000));await open()
 expect(wrapper!.text()).toContain('当前访问较多');expect(wrapper!.text()).not.toContain('internal storage')
 await vi.advanceTimersByTimeAsync(7000);expect(admissionApi.status).toHaveBeenCalledOnce()
 await vi.advanceTimersByTimeAsync(1000);expect(admissionApi.status).toHaveBeenCalledTimes(2)
 vi.mocked(admissionApi.join).mockRejectedValueOnce(new TicketApiError('limit','RATE_LIMITED',429,5000))
 await wrapper!.findAll('button').find(b=>b.text()==='加入队列')!.trigger('click');await vi.advanceTimersByTimeAsync(20)
 expect(wrapper!.text()).toContain('操作较频繁')
})
it('loads direct seat public metadata before login and preserves only a safe waiting destination',async()=>{
 authState.clearAuth();vi.mocked(ticketApi.me).mockRejectedValue(new TicketApiError('Please sign in','UNAUTHENTICATED',401));await router.push({name:routeNames.sessionSeats,params:{sessionId}});await open()
 expect(ticketApi.getSession).toHaveBeenCalledWith(sessionId)
 expect(router.currentRoute.value.name).toBe(routeNames.login)
 expect(router.currentRoute.value.query.redirect).toBe('/events/'+eventId+'/waiting-room?sessionId='+sessionId)
 expect(admissionApi.join).not.toHaveBeenCalled()
})
it('keeps existing selecting checkout release available without admission or availability polling',async()=>{
 const checkout:CheckoutSession={id:'CHK-test',userId:'p18-reader',sessionId,seatIds:['seat-test'],status:'SELECTING',revision:1,createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()}
 sessionStorage.setItem(checkoutLocatorKey()!,JSON.stringify({checkoutSessionId:checkout.id,sessionId}))
 vi.spyOn(ticketApi,'getCheckoutSession').mockResolvedValue(checkout)
 const release=vi.spyOn(ticketApi,'replaceCheckoutSessionSeats').mockResolvedValue({...checkout,seatIds:[],revision:2})
 const availability=vi.spyOn(ticketApi,'getSeatAvailability')
 await router.push({name:routeNames.sessionSeats,params:{sessionId}});await open()
 expect(router.currentRoute.value.name).toBe(routeNames.sessionSeats);expect(availability).not.toHaveBeenCalled()
 await wrapper!.findAll('button').find(b=>b.text()==='释放已选座位')!.trigger('click');await vi.advanceTimersByTimeAsync(20)
 expect(release).toHaveBeenCalledWith(checkout.id,[],1);expect(admissionApi.join).not.toHaveBeenCalled()
})

it('cannot apply a late admission grant after logout',async()=>{
 let finish!:(value:AdmissionStatus)=>void
 vi.mocked(admissionApi.status).mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const availability=vi.spyOn(ticketApi,'getSeatAvailability')
 await router.push({name:routeNames.sessionSeats,params:{sessionId}});await open()
 vi.mocked(ticketApi.me).mockRejectedValue(new TicketApiError('Sign in','UNAUTHENTICATED',401));authState.clearAuth()
 finish(state('ADMITTED'));await vi.advanceTimersByTimeAsync(50)
 expect(authState.currentUser.value).toBeNull();expect(availability).not.toHaveBeenCalled()
 expect(router.currentRoute.value.name).toBe(routeNames.login)
})
