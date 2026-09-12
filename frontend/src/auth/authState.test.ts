import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockData, setMockLatency, ticketApi, TicketApiError } from '../api/ticketApi'
import { authState, checkoutLocatorKey } from './authState'

describe('authenticated account state', () => {
  beforeEach(() => {
    resetMockData()
    setMockLatency(0)
    authState.clearAuth()
    sessionStorage.clear()
  })

  it('restores the current user and logs out through the server API', async () => {
    expect(await authState.refreshMe()).toBeNull()
    await ticketApi.login('demo', 'Ticketing123!')
    expect(await authState.refreshMe()).toMatchObject({ id: 'U-1001', username: 'demo' })
    await authState.logout()
    expect(authState.currentUser.value).toBeNull()
  })

  it('namespaces the checkout locator by authenticated user', async () => {
    expect(checkoutLocatorKey()).toBeNull()
    await authState.login('demo', 'Ticketing123!')
    expect(checkoutLocatorKey()).toBe('ticketing.checkout.U-1001')
    sessionStorage.setItem(checkoutLocatorKey()!, '{"checkoutSessionId":"CHK-1"}')
    await authState.logout()
    expect(sessionStorage.getItem('ticketing.checkout.U-1001')).toBeNull()
  })
})

afterEach(()=>vi.restoreAllMocks())
for(const [name,error,confirmed] of [
 ['success',null,true],['401',new TicketApiError('expired','UNAUTHENTICATED',401),true],
 ['timeout',new Error('timeout'),false],['network',new Error('Network Error'),false],
] as const) it(`logout ${name} clears state and does not restore the server session`,async()=>{
 setMockLatency(0);await authState.login('demo','Ticketing123!')
 const logout=vi.spyOn(ticketApi,'logout');if(error)logout.mockRejectedValue(error)
 const me=vi.spyOn(ticketApi,'me')
 expect(await authState.logout()).toEqual({confirmed})
 expect(authState.currentUser.value).toBeNull();expect(await authState.ensureAuthLoaded()).toBeNull();expect(me).not.toHaveBeenCalled()
})
it('ignores an in-flight me result after logout',async()=>{
 await authState.login('demo','Ticketing123!');const user=authState.currentUser.value!
 let resolve!:(value:typeof user)=>void
 vi.spyOn(ticketApi,'me').mockReturnValue(new Promise(r=>{resolve=r}))
 const pending=authState.refreshMe();await authState.logout();resolve(user);await pending
 expect(authState.currentUser.value).toBeNull()
})
