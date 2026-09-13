import { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockData, setMockLatency, ticketApi, http } from '../src/api/ticketApi'
import { authState, checkoutLocatorKey } from '../src/auth/authState'

function deferred<T>() { let resolve!: (value:T)=>void; const promise=new Promise<T>(done=>{resolve=done}); return {promise,resolve} }
beforeEach(()=>{resetMockData();setMockLatency(0);authState.clearAuth();sessionStorage.clear()})
afterEach(()=>vi.restoreAllMocks())

describe('Phase19 logout invalidates all user polling immediately',()=>{
  it('clears identity and its locator before a slow logout request completes',async()=>{
    await authState.login('demo','Ticketing123!')
    const key=checkoutLocatorKey()!; sessionStorage.setItem(key,'old checkout')
    const response=deferred<void>();vi.spyOn(ticketApi,'logout').mockReturnValueOnce(response.promise)
    const pending=authState.logout()
    expect(authState.currentUser.value).toBeNull()
    expect(sessionStorage.getItem(key)).toBeNull()
    response.resolve();expect(await pending).toEqual({confirmed:true})
  })
  it('does not let an old logout completion erase a later authenticated identity',async()=>{
    await authState.login('demo','Ticketing123!')
    const response=deferred<void>();vi.spyOn(ticketApi,'logout').mockReturnValueOnce(response.promise)
    const pending=authState.logout()
    await authState.login('demo','Ticketing123!')
    response.resolve();await pending
    expect(authState.currentUser.value?.id).toBe('U-1001')
  })
})

function unauthorized(config: InternalAxiosRequestConfig) {
  return new AxiosError('expired', 'ERR_BAD_REQUEST', config, undefined,
    { status:401,statusText:'Unauthorized',headers:{},config,data:{code:'UNAUTHENTICATED',message:'expired'} })
}
it('a late HTTP 401 from an old account cannot clear a later login',async()=>{
  await authState.login('demo','Ticketing123!')
  let reject!:(cause:unknown)=>void;const pending=new Promise<never>((_,fail)=>{reject=fail});let request!:InternalAxiosRequestConfig
  const response=http.get('/notifications',{adapter:config=>{request=config;return pending}})
  const checked=expect(response).rejects.toThrow('expired')
  await vi.waitFor(()=>expect(request).toBeDefined())
  await authState.login('demo','Ticketing123!')
  reject(unauthorized(request))
  await checked
  expect(authState.currentUser.value?.id).toBe('U-1001')
})
it('a current HTTP 401 still clears authentication and stops user polling',async()=>{
  await authState.login('demo','Ticketing123!')
  await expect(http.get('/notifications',{adapter:async config=>{throw unauthorized(config)}})).rejects.toThrow('expired')
  expect(authState.currentUser.value).toBeNull()
})
