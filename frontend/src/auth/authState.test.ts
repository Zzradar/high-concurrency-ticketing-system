import { beforeEach, describe, expect, it } from 'vitest'
import { resetMockData, setMockLatency, ticketApi } from '../api/ticketApi'
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
