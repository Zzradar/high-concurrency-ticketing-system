<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {adminApi,type AdmissionPolicy} from '../../api/adminApi'
import {admissionInteger} from '../../utils/admissionPolicyInput'
import {TicketApiError} from '../../api/ticketApi'
const props=defineProps<{eventId:string}>()
const policy=ref<AdmissionPolicy>(),busy=ref(false),error=ref(''),notice=ref(''),conflict=ref(false)
const mode=ref<AdmissionPolicy['mode']>('OFF')
const fields=[{key:'prequeueSeconds',label:'预排队时间（秒）',min:0,max:86400},{key:'maxActiveUsers',label:'活跃人数上限',min:1,max:1000000},{key:'admissionRatePerSecond',label:'每秒放行人数',min:1,max:100000},{key:'leaseSeconds',label:'资格租约（秒）',min:10,max:3600}] as const
const raw=ref({prequeueSeconds:'',maxActiveUsers:'',admissionRatePerSecond:'',leaseSeconds:''})
let epoch=0
function accept(p:AdmissionPolicy){policy.value=p;mode.value=p.mode;for(const f of fields)raw.value[f.key]=p[f.key]===null?'':String(p[f.key]);conflict.value=false}
async function load(){const e=++epoch;busy.value=true;error.value='';try{const p=await adminApi.admissionPolicy(props.eventId);if(e===epoch)accept(p)}catch{if(e===epoch)error.value='准入策略加载失败，请重试'}finally{if(e===epoch)busy.value=false}}
async function save(){if(!policy.value)return;busy.value=true;error.value='';notice.value='';const e=epoch
 try{const body={mode:mode.value,expectedPolicyVersion:policy.value.policyVersion,
 prequeueSeconds:admissionInteger(raw.value.prequeueSeconds,0,86400),maxActiveUsers:admissionInteger(raw.value.maxActiveUsers,1,1000000),
 admissionRatePerSecond:admissionInteger(raw.value.admissionRatePerSecond,1,100000),leaseSeconds:admissionInteger(raw.value.leaseSeconds,10,3600)}
 const p=await adminApi.saveAdmissionPolicy(props.eventId,body);if(e===epoch){accept(p);notice.value='准入策略已保存'}}catch(ex){if(e===epoch){const code=ex instanceof TicketApiError?ex.code:(ex as {response?:{data?:{code?:string}}}).response?.data?.code;conflict.value=code==='POLICY_VERSION_CONFLICT';error.value=conflict.value?'策略已被其他管理员修改，请重新加载后再保存':ex instanceof Error?ex.message:'准入策略保存失败'}}finally{if(e===epoch)busy.value=false}}
watch(()=>props.eventId,()=>{policy.value=undefined;notice.value='';void load()},{immediate:true})
onBeforeUnmount(()=>{epoch++})
</script>
<template><section class="admin-panel"><h2>准入策略</h2><p>示例数值不是容量结论。未配置时保持关闭；启用前需完成隔离压测。</p><p v-if="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p><button type="button" :disabled="busy" @click="load">重新加载准入策略</button><form v-if="policy" @submit.prevent="save"><p>当前版本：{{policy.policyVersion}}</p><fieldset :disabled="busy||conflict"><label>模式<select v-model="mode" aria-label="准入模式"><option value="OFF">关闭</option><option value="OBSERVE">观察</option><option value="ENFORCED">启用排队</option><option value="PAUSED">暂停放行</option></select></label><div class="admin-grid"><label v-for="f in fields" :key="f.key">{{f.label}}<input v-model="raw[f.key]" :aria-label="f.label" type="text" inputmode="numeric" maxlength="16" required/></label></div><button type="submit">保存准入策略</button></fieldset></form></section></template>
