import {TicketApiError} from '../../api/ticketApi'
import {mount,flushPromises,enableAutoUnmount} from '@vue/test-utils'
import {afterEach,it,expect,vi} from 'vitest'
import Editor from './AdmissionPolicyEditor.vue'
import {adminApi,type AdmissionPolicy} from '../../api/adminApi'
enableAutoUnmount(afterEach)
afterEach(()=>vi.restoreAllMocks())
const off:AdmissionPolicy={eventId:'e',mode:'OFF',policyVersion:0,prequeueSeconds:null,maxActiveUsers:null,admissionRatePerSecond:null,leaseSeconds:null,queueGeneration:null}
async function fill(w:ReturnType<typeof mount>){for(const [label,value] of [['预排队时间（秒）','0'],['活跃人数上限','10'],['每秒放行人数','2'],['资格租约（秒）','30']])await w.get(`input[aria-label="${label}"]`).setValue(value)}
it('loads synthetic OFF without inventing capacities; saves strict values and expected version',async()=>{
 vi.spyOn(adminApi,'admissionPolicy').mockResolvedValue(off)
 const save=vi.spyOn(adminApi,'saveAdmissionPolicy').mockResolvedValue({...off,policyVersion:1})
 const w=mount(Editor,{props:{eventId:'e'}});await flushPromises()
 expect(w.get('select').element.value).toBe('OFF')
 expect(w.findAll('input').every(i=>(i.element as HTMLInputElement).value==='')).toBe(true)
 await fill(w)
 for(const raw of ['1e2',' 10','1.0','-1','1000001']){await w.get('input[aria-label="活跃人数上限"]').setValue(raw);await w.get('form').trigger('submit');await flushPromises();expect(save).not.toHaveBeenCalled()}
 await fill(w);await w.get('form').trigger('submit');await flushPromises()
 expect(save).toHaveBeenCalledWith('e',{mode:'OFF',expectedPolicyVersion:0,prequeueSeconds:0,maxActiveUsers:10,admissionRatePerSecond:2,leaseSeconds:30})
 expect(w.text()).toContain('当前版本：1')
})
it.each([new TicketApiError('Conflict','POLICY_VERSION_CONFLICT',409),{response:{data:{code:'POLICY_VERSION_CONFLICT'}}}])('requires explicit reload after OCC conflict and does not retry a PUT (%s)',async(error)=>{
 const load=vi.spyOn(adminApi,'admissionPolicy').mockResolvedValue(off)
 const save=vi.spyOn(adminApi,'saveAdmissionPolicy').mockRejectedValue(error)
 const w=mount(Editor,{props:{eventId:'e'}});await flushPromises();await fill(w);await w.get('form').trigger('submit');await flushPromises()
 expect(save).toHaveBeenCalledTimes(1);expect(w.get('fieldset').attributes('disabled')).toBeDefined()
 expect(w.text()).toContain('其他管理员修改')
 await w.findAll('button')[0]!.trigger('click');await flushPromises();expect(load).toHaveBeenCalledTimes(2)
 expect(w.get('fieldset').attributes('disabled')).toBeUndefined()
})
it('ignores a response after event change and unmount',async()=>{
 let resolve!:(p:AdmissionPolicy)=>void
 vi.spyOn(adminApi,'admissionPolicy').mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValue({...off,eventId:'new',policyVersion:3})
 const w=mount(Editor,{props:{eventId:'old'}});await w.setProps({eventId:'new'});await flushPromises()
 resolve({...off,eventId:'old',policyVersion:1});await flushPromises();expect(w.text()).toContain('当前版本：3');w.unmount()
})
