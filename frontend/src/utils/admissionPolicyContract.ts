import type { AdmissionPolicy } from '../api/adminApi'
const integer=(v:unknown,min:number,max:number):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=min&&v<=max
export function requireAdmissionPolicy(value:unknown,eventId:string):AdmissionPolicy {
 const fail=()=>{throw new Error('准入策略数据暂不可用，请重新加载')}
 if(!value||typeof value!=='object'||Array.isArray(value))return fail()
 const v=value as Record<string,unknown>
 if(v.eventId!==eventId||!['OFF','OBSERVE','PAUSED','ENFORCED'].includes(v.mode as string)||!integer(v.policyVersion,0,Number.MAX_SAFE_INTEGER))return fail()
 if(v.policyVersion===0){
  if(v.mode!=='OFF'||['prequeueSeconds','maxActiveUsers','admissionRatePerSecond','leaseSeconds','queueGeneration'].some(k=>v[k]!==null))return fail()
 }else if(!integer(v.prequeueSeconds,0,86400)||!integer(v.maxActiveUsers,1,1000000)||!integer(v.admissionRatePerSecond,1,100000)||!integer(v.leaseSeconds,10,3600)||typeof v.queueGeneration!=='string'||!/^[a-f0-9]{32}$/.test(v.queueGeneration))return fail()
 return value as AdmissionPolicy
}
