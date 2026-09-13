import { expect, it } from 'vitest'
import { mutateAuthentication, authenticationSettled } from '../src/api/authTransport'
function deferred() { let resolve!: () => void; const promise = new Promise<void>(r => { resolve = r }); return { promise, resolve } }
it('holds B behind A response and discarded-cookie cleanup', async () => {
  const response = deferred(), cleanup = deferred(); const trace: string[] = []
  const a = mutateAuthentication(async () => { trace.push('A'); await response.promise; trace.push('cleanup'); await cleanup.promise })
  const b = mutateAuthentication(async () => { trace.push('B') })
  await Promise.resolve(); expect(trace).toEqual(['A'])
  response.resolve(); await Promise.resolve(); expect(trace).toEqual(['A', 'cleanup'])
  cleanup.resolve(); await Promise.all([a, b]); expect(trace).toEqual(['A', 'cleanup', 'B'])
})
it('failure does not poison subsequent login or the me barrier', async () => {
  const a = mutateAuthentication(async () => { throw new Error('A failed') })
  const observed = expect(a).rejects.toThrow('A failed')
  let user = ''
  const b = mutateAuthentication(async () => { user = 'B' })
  await authenticationSettled(); expect(user).toBe('B'); await b; await observed
})
it('me waits for a logout enqueued while an earlier mutation is pending', async () => {
  const response = deferred(); let user = 'A'
  const a = mutateAuthentication(async () => { await response.promise })
  const read = authenticationSettled().then(() => user)
  const logout = mutateAuthentication(async () => { user = '' })
  response.resolve(); expect(await read).toBe(''); await Promise.all([a, logout])
})
