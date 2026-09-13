import { describe, expect, it, vi } from 'vitest'
import { SingleFlight } from '../src/utils/singleFlight'

function deferred<T>() { let resolve!: (value:T)=>void; let reject!: (cause:unknown)=>void; const promise=new Promise<T>((done,fail)=>{resolve=done;reject=fail}); return {promise,resolve,reject} }

describe('Phase19 single-flight lifecycle reads', () => {
  it('shares a pending request for the same business identity', async () => {
    const reads=new SingleFlight<number>(), pending=deferred<number>(), request=vi.fn(()=>pending.promise)
    const first=reads.run('A',request), second=reads.run('A',request)
    await Promise.resolve(); expect(request).toHaveBeenCalledTimes(1)
    pending.resolve(7); expect(await first).toBe(7); expect(await second).toBe(7)
  })
  it('drains an obsolete identity before issuing the next identity request', async () => {
    const reads=new SingleFlight<number>(), pending=deferred<number>()
    let identity='A'
    const first=reads.run('A',()=>pending.promise,()=>identity==='A')
    await Promise.resolve(); identity='B'
    const next=vi.fn(async()=>2), second=reads.run('B',next,()=>identity==='B')
    await Promise.resolve(); expect(next).not.toHaveBeenCalled()
    pending.resolve(1); expect(await first).toBeUndefined(); expect(await second).toBe(2)
    expect(next).toHaveBeenCalledTimes(1)
  })
  it('never dispatches a queued request whose lifecycle already ended', async () => {
    const reads=new SingleFlight<number>(), pending=deferred<number>()
    let current=true
    const first=reads.run('A',()=>pending.promise)
    await Promise.resolve()
    const next=vi.fn(async()=>2), second=reads.run('B',next,()=>current)
    current=false; pending.resolve(1)
    await first; expect(await second).toBeUndefined(); expect(next).not.toHaveBeenCalled()
  })
  it('releases failures and allows a queued identity without hiding the original rejection', async () => {
    const reads=new SingleFlight<number>(), pending=deferred<number>()
    const first=reads.run('A',()=>pending.promise)
    const failure=expect(first).rejects.toThrow('offline')
    await Promise.resolve()
    const second=reads.run('B',async()=>2)
    pending.reject(new Error('offline')); await failure
    expect(await second).toBe(2)
    expect(await reads.run('B',async()=>3)).toBe(3)
  })
})
