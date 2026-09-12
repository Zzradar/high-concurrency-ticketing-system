import type { AdmissionStatus } from '../types'
import { nextPollDelay } from './pollingPolicy'
type Operation='status'|'join'|'heartbeat'|'leave'
interface Options {
 request:(operation:Operation,generation?:string)=>Promise<AdmissionStatus>
 update:(value:AdmissionStatus)=>void
 error:(cause:unknown)=>void
 hidden:()=>boolean
 now?:()=>number
 rng?:()=>number
 leaseOnly?:boolean
}
// One active operation and one timer; status never postpones the independent heartbeat due time.
export class AdmissionPolling {
 private timer:ReturnType<typeof setTimeout>|undefined
 private work:Promise<AdmissionStatus|undefined>|undefined
 private epoch=0
 private stopped=false
 private nextStatus=Infinity
 private nextHeartbeat=Infinity
 private generation:string|undefined
 private errors=0
 private current:AdmissionStatus|undefined
 private wasHidden=false
 private readonly now:()=>number
 private readonly options:Options
 constructor(options:Options){this.options=options;this.now=options.now??Date.now;this.wasHidden=options.hidden()}
 start(initial?:AdmissionStatus){
  if(initial){this.apply(initial,'status');this.schedule()}
  else{this.nextStatus=this.now();void this.execute('status')}
 }
 private apply(value:AdmissionStatus,op:Operation){
  this.current=value;this.generation=value.queueGeneration??undefined;this.errors=0
  const now=this.now()
  this.nextStatus=this.options.leaseOnly?Infinity:now+nextPollDelay({pollAfterMs:value.pollAfterMs,emptyStreak:0,errorStreak:0},this.options.rng)
  if(value.heartbeatAfterMs===null)this.nextHeartbeat=Infinity
  else if(op==='heartbeat'||op==='join'||this.nextHeartbeat===Infinity)this.nextHeartbeat=now+value.heartbeatAfterMs
  if(['RESET_REQUIRED','SALES_ENDED','NOT_REQUIRED'].includes(value.state)){this.nextStatus=Infinity;this.nextHeartbeat=Infinity}
  this.options.update(value)
 }
 private schedule(){
  if(this.timer!==undefined)clearTimeout(this.timer);this.timer=undefined
  if(this.stopped||this.work||this.options.hidden())return
  const next=Math.min(this.nextStatus,this.nextHeartbeat)
  if(!Number.isFinite(next))return
  this.timer=setTimeout(()=>{this.timer=undefined;void this.execute(this.nextStatus<=this.nextHeartbeat?'status':'heartbeat')},Math.max(0,next-this.now()))
 }
 private execute(op:Operation):Promise<AdmissionStatus|undefined>{
  if(this.stopped||this.options.hidden())return Promise.resolve(undefined)
  if(this.work)return this.work
  if(this.timer!==undefined)clearTimeout(this.timer);this.timer=undefined
  const epoch=this.epoch
  this.work=(async()=>{
   try{
    const value=await this.options.request(op,this.generation)
    if(this.stopped||epoch!==this.epoch)return
    this.apply(value,op);return value
   }catch(cause){
    if(this.stopped||epoch!==this.epoch)return
    this.errors=Math.min(5,this.errors+1)
    const retry=typeof cause==='object'&&cause!==null&&'retryAfterMs' in cause&&typeof cause.retryAfterMs==='number'?cause.retryAfterMs:undefined
    const delay=nextPollDelay({pollAfterMs:this.current?.pollAfterMs,emptyStreak:0,errorStreak:this.errors,retryAfterMs:retry},this.options.rng)
    // A failure cannot cause an already-due heartbeat to spin immediately.
    this.nextStatus=this.now()+delay;this.nextHeartbeat=Infinity
    this.options.error(cause)
   }
  })()
  return this.work.finally(()=>{this.work=undefined;this.schedule()})
 }
 async join(reset=false){if(this.work)await this.work;if(reset)this.generation=undefined;return this.execute('join')}
 async leave(){if(this.work)await this.work;return this.execute('leave')}
 visibility(){
  if(this.options.hidden()){this.wasHidden=true;if(this.timer!==undefined)clearTimeout(this.timer);this.timer=undefined;return}
  if(!this.wasHidden)return
  this.wasHidden=false;this.nextStatus=this.now()
  // An old request drains first; then the authoritative GET runs before any heartbeat.
  if(this.work){const pending=this.work;void pending.finally(()=>{if(!this.stopped){this.nextStatus=this.now();this.schedule()}})}
  else void this.execute('status')
 }
 stop(){this.stopped=true;this.epoch++;if(this.timer!==undefined)clearTimeout(this.timer);this.timer=undefined}
}
