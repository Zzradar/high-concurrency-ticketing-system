import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { refundFixture } from '../test/refundFixtures'
import type { CreateRefundResult, Refund } from '../types'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.resetModules(); document.cookie = 'ticketing_csrf=; Max-Age=0; path=/' })

async function realApi(adapter: AxiosAdapter) {
  vi.resetModules()
  vi.stubEnv('MODE', 'development')
  vi.stubEnv('VITE_USE_MOCK_API', 'false')
  const create = axios.create.bind(axios)
  vi.spyOn(axios, 'create').mockImplementation((config) => create({ ...config, adapter }))
  return import('./ticketApi')
}

describe('Refund HTTP contract through the existing Axios client', () => {
  it.each([
    [202, 'CREATED', 'PROCESSING'],
    [202, 'REUSED_PROCESSING', 'PROCESSING'],
    [200, 'REUSED_TERMINAL', 'SUCCEEDED'],
    [200, 'REUSED_TERMINAL', 'FAILED'],
  ] as const)('parses HTTP %s %s / %s with no body and existing CSRF', async (status, disposition, refundStatus) => {
    const data: CreateRefundResult = { disposition, refund: { ...refundFixture, status: refundStatus }, pollAfterMs: 2000 }
    let sent: InternalAxiosRequestConfig | undefined
    const { ticketApi, isMockMode } = await realApi(async (config) => {
      sent = config
      return { data, status, statusText: 'OK', headers: {}, config }
    })
    document.cookie = 'ticketing_csrf=test-csrf; path=/'
    expect(isMockMode).toBe(false)
    expect(await ticketApi.createRefund('O1')).toEqual(data)
    expect(sent?.url).toBe('/orders/O1/refunds')
    expect(sent?.method).toBe('post')
    // Adapter sees the data AFTER Axios request transforms, not just a mocked post call.
    expect(sent?.data).toBeUndefined()
    expect(sent?.headers.get('X-CSRF-Token')).toBe('test-csrf')
    expect(sent?.withCredentials).toBe(true)
    expect(sent?.baseURL).toBe('/api')
  })

  it('GET returns the complete resource, including optional terminal fields, without a wrapper', async () => {
    const data: Refund = { ...refundFixture, status: 'FAILED', failedAt: '2026-09-09T02:01:00.000Z', failureCode: 'PROVIDER_REFUND_FAILED' }
    const adapter = vi.fn<AxiosAdapter>(async (config) => ({ config, data, status: 200, statusText: 'OK', headers: {} }))
    const { ticketApi } = await realApi(adapter)
    expect(await ticketApi.getRefund('RFD-test')).toEqual(data)
    expect(adapter.mock.calls[0]?.[0]).toMatchObject({ method: 'get', url: '/refunds/RFD-test', withCredentials: true })
  })

  it.each(['ORDER_NOT_REFUNDABLE', 'REFUND_WINDOW_CLOSED', 'REFUND_NOT_FOUND', 'CSRF_INVALID'])('retains normalized error code %s', async (code) => {
    const { ticketApi, TicketApiError } = await realApi(async (config) => {
      throw new AxiosError('request failed', 'ERR_BAD_REQUEST', config, undefined, { config, status: 409, statusText: 'Conflict', headers: {}, data: { code, message: code } })
    })
    await expect(ticketApi.createRefund('O1')).rejects.toBeInstanceOf(TicketApiError)
    await expect(ticketApi.getRefund('RFD-test')).rejects.toMatchObject({ code })
  })
})
