import axios from 'axios'
import { afterEach, expect, it, vi } from 'vitest'
afterEach(() => {vi.unstubAllEnvs();vi.resetModules()})
it('anonymous cleanup 401 preserves the active login credential error', async () => {
  vi.resetModules();vi.stubEnv('MODE','development');vi.stubEnv('VITE_USE_MOCK_API','false')
  const {ticketApi,http}=await import('../src/api/ticketApi')
  http.defaults.adapter=async config => {
    const login=config.url==='/auth/login'
    const response={status:401,statusText:'Unauthorized',headers:{},config,data:{code:login?'INVALID_CREDENTIALS':'UNAUTHENTICATED',message:login?'Invalid username or password':'Authentication required'}}
    throw new axios.AxiosError('Unauthorized','ERR_BAD_REQUEST',config,undefined,response)
  }
  await expect(ticketApi.login('a','wrong')).rejects.toMatchObject({code:'INVALID_CREDENTIALS'})
})
