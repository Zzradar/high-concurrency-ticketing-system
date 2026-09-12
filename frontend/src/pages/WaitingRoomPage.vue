<script setup lang="ts">
import { computed,onBeforeUnmount,onMounted,ref,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { authState } from '../auth/authState'
import { ticketApi } from '../api/ticketApi'
import { admissionApi,admissionErrorText } from '../api/admissionApi'
import { AdmissionPolling } from '../utils/admissionPolling'
import { safeSessionId } from '../utils/admissionContract'
import { routeNames,setPageTitle } from '../navigation'
import type { AdmissionStatus,TicketEvent } from '../types'
const route=useRoute(),router=useRouter()
const event=ref<TicketEvent>(),status=ref<AdmissionStatus>(),error=ref(''),busy=ref(false),loading=ref(true)
let poller:AdmissionPolling|undefined,epoch=0,disposed=false
let targetSession:string|undefined
const descriptions:Record<AdmissionStatus['state'],string>={NOT_REQUIRED:'当前活动无需排队。',NOT_JOINED:'你尚未加入队列。',PREQUEUED:'已登记排队，开售后将安排进入。',WAITING:'正在排队，请保持此页面打开。',ADMITTED:'现在可以进入选座。',RESET_REQUIRED:'本次队列已更新，请重新加入。',SALES_ENDED:'本场售票已结束。',PAUSED:'暂缓放行，你的排队位置会保留。'}
const position=computed(()=>status.value?.positionApprox===null||status.value?.positionApprox===undefined?null:Math.max(0,status.value.positionApprox-1))
function returnTarget(){return targetSession?{name:routeNames.sessionSeats,params:{sessionId:targetSession}}:{name:routeNames.eventSessions,params:{eventId:event.value!.id}}}
function login(){void router.replace({name:routeNames.login,query:{redirect:router.resolve({name:routeNames.waitingRoom,params:{eventId:event.value!.id},query:targetSession?{sessionId:targetSession}:{}}).fullPath}})}
async function load(){
 const current=++epoch;poller?.stop();status.value=undefined;error.value='';loading.value=true
 try {
  if(!safeSessionId(route.params.eventId) || (route.query.sessionId!==undefined&&!safeSessionId(route.query.sessionId)))throw new Error('Invalid destination')
  targetSession=route.query.sessionId as string|undefined
  const loaded=await ticketApi.getEvent(route.params.eventId)
  if(targetSession){const session=await ticketApi.getSession(targetSession);if(session.eventId!==loaded.id)throw new Error('Mismatched destination')}
  if(disposed||current!==epoch)return
  event.value=loaded;setPageTitle(loaded.name+' · 排队')
  if(loaded.admission?.required===false){void router.replace(returnTarget());return}
  if(!authState.currentUser.value){login();return}
  poller=new AdmissionPolling({hidden:()=>document.hidden,
   request:(op,generation)=>op==='status'?admissionApi.status(loaded.id,generation):op==='join'?admissionApi.join(loaded.id,generation):op==='leave'?admissionApi.leave(loaded.id,generation):admissionApi.heartbeat(loaded.id,generation!),
   update:value=>{if(disposed||current!==epoch)return;status.value=value;error.value='';if(!document.hidden&&['ADMITTED','NOT_REQUIRED'].includes(value.state)){poller?.stop();void router.replace(returnTarget())}},
   error:cause=>{if(current===epoch&&!disposed)error.value=admissionErrorText(cause)},
  });poller.start()
 }catch{if(current===epoch&&!disposed)error.value='无法打开排队页，请检查活动和场次后重试。'}
 finally{if(current===epoch)loading.value=false}
}
async function join(){if(busy.value)return;busy.value=true;try{await poller?.join(status.value?.state==='RESET_REQUIRED')}finally{busy.value=false}}
async function leave(){if(busy.value)return;busy.value=true;try{await poller?.leave()}finally{busy.value=false}}
function visibility(){poller?.visibility()}
onMounted(()=>{void load();document.addEventListener('visibilitychange',visibility)})
onBeforeUnmount(()=>{disposed=true;epoch++;poller?.stop();document.removeEventListener('visibilitychange',visibility)})
watch(()=>[route.params.eventId,route.query.sessionId],()=>{void load()})
watch(()=>authState.currentUser.value?.id,()=>{poller?.stop();if(!disposed&&event.value){if(!authState.currentUser.value)login();else void load()}})
</script>
<template>
 <main class="page-shell auth-page">
  <section class="selection-panel auth-card" aria-labelledby="waiting-title">
   <h1 id="waiting-title">{{ event?.name ?? '活动排队' }}</h1>
   <p v-if="loading" role="status">正在获取排队信息…</p>
   <template v-if="status">
    <p class="waiting-state" role="status">{{ descriptions[status.state] }}</p>
    <p v-if="position!==null" class="waiting-position">前方约 {{ position }} 人</p>
    <p v-if="['PREQUEUED','WAITING','PAUSED'].includes(status.state)">离开或隐藏页面较久后，需要重新排队。</p>
    <button v-if="['NOT_JOINED','RESET_REQUIRED'].includes(status.state)" class="primary-button" :disabled="busy||!status.joinAllowed" @click="join">{{ status.state==='RESET_REQUIRED'?'重新加入队列':status.joinAllowed?'加入队列':'排队尚未开放' }}</button>
    <button v-if="['PREQUEUED','WAITING','PAUSED'].includes(status.state)" class="secondary-button" :disabled="busy" @click="leave">离开队列</button>
   </template>
   <p v-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</p>
   <button v-if="error&&!loading" class="secondary-button" @click="load">重新获取信息</button>
   <RouterLink :to="{name:routeNames.orders}">查看现有订单</RouterLink>
   <RouterLink v-if="event" :to="{name:routeNames.eventSessions,params:{eventId:event.id}}">返回场次列表</RouterLink>
  </section>
 </main>
</template>
