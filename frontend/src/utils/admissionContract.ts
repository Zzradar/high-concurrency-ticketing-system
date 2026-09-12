import type { AdmissionStatus,AdmissionSummary } from '../types'
import { validPollHint } from './pollingPolicy'
import { instant } from './timeContract'
const record=(v:unknown):v is Record<string,unknown>=>typeof v==='object' && v!==null && !Array.isArray(v)
export function isAdmissionSummary(v:unknown):v is AdmissionSummary {
 if(!record(v)||typeof v.required!=='boolean'||typeof v.state!=='string'||!['NOT_REQUIRED','PREQUEUE','OPEN','PAUSED','SALES_ENDED','UNAVAILABLE'].includes(v.state))return false
 if(v.prequeueStartsAt!==null&&!instant(v.prequeueStartsAt))return false
 return v.required?v.state!=='NOT_REQUIRED':v.state==='NOT_REQUIRED'&&v.prequeueStartsAt===null
}
export function isAdmissionStatus(v:unknown):v is AdmissionStatus {
 if(!record(v)||typeof v.state!=='string'||!['NOT_REQUIRED','NOT_JOINED','PREQUEUED','WAITING','ADMITTED','RESET_REQUIRED','SALES_ENDED','PAUSED'].includes(v.state))return false
 if(!validPollHint(v.pollAfterMs)||!instant(v.serverTime)||typeof v.joinAllowed!=='boolean')return false
 if(v.queueGeneration!==null&&(typeof v.queueGeneration!=='string'||! /^[a-f0-9]{32}$/.test(v.queueGeneration)))return false
 if(v.positionApprox!==null&&(typeof v.positionApprox!=='number'||!Number.isSafeInteger(v.positionApprox)||v.positionApprox<1||v.positionApprox>Number.MAX_SAFE_INTEGER))return false
 if(v.heartbeatAfterMs!==null&&(typeof v.heartbeatAfterMs!=='number'||!Number.isSafeInteger(v.heartbeatAfterMs)||v.heartbeatAfterMs<1000||v.heartbeatAfterMs>10000))return false
 if(v.admittedUntil!==null&&!instant(v.admittedUntil))return false
 if(v.state==='NOT_REQUIRED')return v.queueGeneration===null && v.admittedUntil===null && v.heartbeatAfterMs===null
 return v.queueGeneration!==null && (v.state==='ADMITTED'?v.admittedUntil!==null:v.admittedUntil===null)
}
export function safeSessionId(value:unknown):value is string {return typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)}
export function safeInternalRedirect(value:unknown):value is string {
 if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||/[\\\x00-\x20]/.test(value))return false
 try{const decoded=decodeURIComponent(value);return !decoded.startsWith('//')&&!/[\\\x00-\x20]/.test(decoded)}catch{return false}
}
