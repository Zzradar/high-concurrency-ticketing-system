import { http,TicketApiError,isMockMode } from './ticketApi'
import { isAdmissionStatus } from '../utils/admissionContract'
import type { AdmissionStatus } from '../types'
function validate(value:unknown):AdmissionStatus {
 if(!isAdmissionStatus(value))throw new TicketApiError('排队信息暂不可用，请稍后重试。','INVALID_ADMISSION_RESPONSE')
 return value
}
const off=():AdmissionStatus=>({state:'NOT_REQUIRED',queueGeneration:null,positionApprox:null,admittedUntil:null,pollAfterMs:2000,heartbeatAfterMs:null,serverTime:new Date().toISOString(),joinAllowed:false})
const path=(event:string)=>'/events/'+encodeURIComponent(event)+'/admission'
export const admissionApi={
 async status(event:string,generation?:string){return isMockMode?off():validate((await http.get(path(event),{params:generation?{queueGeneration:generation}:{}})).data)},
 async join(event:string,generation?:string){return isMockMode?off():validate((await http.post(path(event),generation?{queueGeneration:generation}:{})).data)},
 async heartbeat(event:string,generation:string){return isMockMode?off():validate((await http.post(path(event)+'/heartbeat',{queueGeneration:generation})).data)},
 async leave(event:string,generation?:string){return isMockMode?off():validate((await http.delete(path(event),{data:generation?{queueGeneration:generation}:{}})).data)},
}
export function admissionErrorText(cause:unknown):string {
 if(cause instanceof TicketApiError){
  if(cause.status===429)return '操作较频繁，请稍候再试。'
  if(cause.status===503)return '当前访问较多，请稍候，我们会自动重试。'
  if(cause.code==='ADMISSION_REQUIRED')return '请先完成排队，再继续选座。'
  if(cause.code==='ADMISSION_NOT_OPEN')return '排队尚未开放，请稍候。'
  if(cause.status===401)return '登录已失效，请重新登录后继续。'
 }
 return '排队信息暂未更新，请稍后重试。'
}
