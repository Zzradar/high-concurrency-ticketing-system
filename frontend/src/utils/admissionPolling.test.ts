import { afterEach,beforeEach,expect,it,vi } from 'vitest'
import { AdmissionPolling } from './admissionPolling'
import { isAdmissionStatus,isAdmissionSummary,safeInternalRedirect,safeSessionId } from './admissionContract'
import type { AdmissionStatus } from '../types'
const waiting=():AdmissionStatus=>({state:'WAITING',queueGeneration:'a'.repeat(32),positionApprox:2,admittedUntil:null,pollAfterMs:2000,heartbeatAfterMs:5000,serverTime:new Date().toISOString(),joinAllowed:true})
let poller:AdmissionPolling|undefined
beforeEach(()=>vi.useFakeTimers());afterEach(()=>{poller?.stop();vi.useRealTimers()})
it('keeps heartbeat independent from GET, stops hidden, and performs GET before resuming heartbeats',async()=>{
 let hidden=false
 const request=vi.fn(async(_op:string,_generation?:string)=>waiting())
 poller=new AdmissionPolling({request,update:vi.fn(),error:vi.fn(),hidden:()=>hidden,rng:()=>.5})
 poller.start();await vi.advanceTimersByTimeAsync(5100)
 expect(request.mock.calls.map(c=>c[0])).toEqual(['status','status','status','heartbeat'])
 hidden=true;poller.visibility();await vi.advanceTimersByTimeAsync(30000);expect(request).toHaveBeenCalledTimes(4)
 hidden=false;poller.visibility();await vi.advanceTimersByTimeAsync(1);expect(request.mock.calls[4]![0]).toBe('status')
 poller.stop();const count=request.mock.calls.length;await vi.advanceTimersByTimeAsync(60000);expect(request).toHaveBeenCalledTimes(count)
})
it('serializes delayed reads, requires explicit join after reset, and fences unmounted results',async()=>{
 let finish!:(v:AdmissionStatus)=>void
 const request=vi.fn((_op:string,_generation?:string)=>new Promise<AdmissionStatus>(r=>{finish=r}));const update=vi.fn()
 poller=new AdmissionPolling({request,update,error:vi.fn(),hidden:()=>false,rng:()=>.5});poller.start()
 await vi.advanceTimersByTimeAsync(20000);expect(request).toHaveBeenCalledOnce()
 finish({...waiting(),state:'RESET_REQUIRED',positionApprox:null,heartbeatAfterMs:null});await vi.advanceTimersByTimeAsync(60000);expect(request).toHaveBeenCalledOnce()
 const joining=poller.join(true);expect(request.mock.calls[1]).toEqual(['join',undefined])
 poller.stop();finish(waiting());await joining;expect(update).toHaveBeenCalledOnce()
})
it('checks strict queue/public types and forbids external or malformed destinations',()=>{
 expect(isAdmissionStatus(waiting())).toBe(true)
 for(const bad of ['2000',[],true,null,2000.1])expect(isAdmissionStatus({...waiting(),pollAfterMs:bad})).toBe(false)
 expect(isAdmissionStatus({...waiting(),positionApprox:0})).toBe(false)
 expect(isAdmissionSummary({required:'false',state:'NOT_REQUIRED',prequeueStartsAt:null})).toBe(false)
 for(const bad of ['//evil.example','/\\evil.example','/%2f%2fevil.example','https://evil.example',[],{}])expect(safeInternalRedirect(bad)).toBe(false)
 expect(safeInternalRedirect('/events/EVT-1/waiting-room?sessionId=S-1')).toBe(true)
 for(const bad of [[],{},'../x','//x','x?next=evil'])expect(safeSessionId(bad)).toBe(false)
})

it('waits for real visibility when the page initially loads hidden',async()=>{
 let hidden=true;const request=vi.fn(async(_op:string,_generation?:string)=>waiting())
 poller=new AdmissionPolling({request,update:vi.fn(),error:vi.fn(),hidden:()=>hidden,rng:()=>.5});poller.start()
 await vi.advanceTimersByTimeAsync(30000);expect(request).not.toHaveBeenCalled()
 hidden=false;poller.visibility();await vi.advanceTimersByTimeAsync(1);expect(request).toHaveBeenCalledOnce()
})
