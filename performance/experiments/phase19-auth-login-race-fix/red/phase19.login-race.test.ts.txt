import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '../src/App.vue'
import LoginView from '../src/pages/LoginView.vue'
import { authState } from '../src/auth/authState'
import { ticketApi, resetMockData, setMockLatency, TicketApiError } from '../src/api/ticketApi'
import type { CurrentUser } from '../src/types'

const A: CurrentUser={id:'A',username:'a',displayName:'User A',role:'CUSTOMER'}
const B: CurrentUser={id:'B',username:'b',displayName:'User B',role:'CUSTOMER'}
function deferred<T>() {let resolve!:(v:T)=>void;let reject!:(e:unknown)=>void;const promise=new Promise<T>((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
enableAutoUnmount(afterEach)
beforeEach(()=>{resetMockData();setMockLatency(0);authState.clearAuth();vi.spyOn(ticketApi,'logout').mockResolvedValue();vi.spyOn(ticketApi,'me').mockRejectedValue(new TicketApiError('anonymous','UNAUTHENTICATED',401))})
afterEach(()=>vi.restoreAllMocks())
async function page() {
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/login',name:'login',component:LoginView},{path:'/events',name:'events',component:{template:'<p>Events</p>'}},{path:'/away',component:{template:'<p>Away</p>'}}]})
 await router.push('/login');await router.isReady()
 const notifications=vi.spyOn(ticketApi,'getNotifications').mockResolvedValue([])
 const wrapper=mount(App,{global:{plugins:[router],stubs:{RouterLink:true}}});await flushPromises()
 const submit=async()=>{await wrapper.get('input[name=username]').setValue('a');await wrapper.get('input[name=password]').setValue('password');await wrapper.get('form').trigger('submit');await flushPromises()}
 return {router,wrapper,notifications,submit}
}
it('A pending then logout then A success stays anonymous, does not navigate or restart notification polling',async()=>{
 const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise)
 const p=await page();await p.submit();await authState.logout();a.resolve(A);await flushPromises()
 expect(authState.currentUser.value).toBeNull();expect(p.router.currentRoute.value.path).toBe('/login');expect(p.notifications).not.toHaveBeenCalled()
})
it('A pending then B succeeds then A succeeds cannot replace B',async()=>{
 const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise).mockResolvedValueOnce(B)
 const old=authState.login('a','pw');await authState.login('b','pw');a.resolve(A);expect(await old).toBeNull();expect(authState.currentUser.value).toEqual(B)
})
it('leaving LoginView invalidates its pending login at global authState boundary',async()=>{
 const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise)
 const p=await page();await p.submit();await p.router.push('/away');a.resolve(A);await flushPromises()
 expect(authState.currentUser.value).toBeNull();expect(p.router.currentRoute.value.path).toBe('/away');expect(p.notifications).not.toHaveBeenCalled()
})
it('late A failure after B success cannot show its error, navigate, or clear B',async()=>{
 const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise).mockResolvedValueOnce(B)
 const p=await page();await p.submit();await authState.login('b','pw');a.reject(new TicketApiError('obsolete A failure','BAD_PASSWORD',401));await flushPromises()
 expect(authState.currentUser.value).toEqual(B);expect(p.wrapper.text()).not.toContain('obsolete A failure');expect(p.router.currentRoute.value.path).toBe('/login')
})
it('valid login still publishes user, navigates and starts notification reads',async()=>{
 vi.spyOn(ticketApi,'login').mockResolvedValueOnce(B)
 const p=await page();await p.submit();await flushPromises()
 expect(authState.currentUser.value).toEqual(B);expect(p.router.currentRoute.value.path).toBe('/events');expect(p.notifications).toHaveBeenCalledTimes(1)
})
it('clearAuth rejects late login writes and initialization',async()=>{
 const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise)
 const old=authState.login('a','pw');authState.clearAuth();a.resolve(A);expect(await old).toBeNull();expect(await authState.ensureAuthLoaded()).toBeNull()
})
it('cancel signal invalidates only its own pending login, not a newer B operation',async()=>{
 const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise).mockResolvedValueOnce(B)
 const controller=new AbortController();const old=authState.login('a','pw',{signal:controller.signal});await authState.login('b','pw');controller.abort();a.resolve(A);await old
 expect(authState.currentUser.value).toEqual(B)
})
it('old me finally cannot clear loading or initialize a pending login',async()=>{
 const me=deferred<CurrentUser>();vi.mocked(ticketApi.me).mockReturnValueOnce(me.promise)
 const refresh=authState.refreshMe();const a=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise)
 const pending=authState.login('a','pw');me.resolve(B);await refresh
 expect(authState.authLoading.value).toBe(true);expect(authState.currentUser.value).toBeNull();a.resolve(A);await pending;expect(authState.authLoading.value).toBe(false)
})
it('old me after logout cannot restore the user',async()=>{
 const me=deferred<CurrentUser>();vi.mocked(ticketApi.me).mockReturnValueOnce(me.promise)
 const old=authState.refreshMe();await authState.logout();me.resolve(A);await old;expect(authState.currentUser.value).toBeNull()
})
it('older login success cannot clear newer login loading',async()=>{
 const a=deferred<CurrentUser>();const b=deferred<CurrentUser>();vi.spyOn(ticketApi,'login').mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
 const old=authState.login('a','pw');const current=authState.login('b','pw');a.resolve(A);await old
 expect(authState.currentUser.value).toBeNull();expect(authState.authLoading.value).toBe(true);b.resolve(B);await current;expect(authState.currentUser.value).toEqual(B)
})
