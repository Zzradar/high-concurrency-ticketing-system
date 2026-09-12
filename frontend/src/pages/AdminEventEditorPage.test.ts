import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import Page from './AdminEventEditorPage.vue'
import { adminApi, type AdminEventDetail } from '../api/adminApi'
enableAutoUnmount(afterEach)
afterEach(()=>vi.restoreAllMocks())
it('never sends invalid raw prices, sends exact cents, and roundtrips saved prices',async()=>{
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/admin/events/:eventId',component:Page}]})
 await router.push('/admin/events/e')
 const venue={id:'v',name:'V',city:'C',totalSeats:1,zoneCount:1,frozen:false,zones:[{id:'z',code:'Z',name:'内场',sortOrder:0,seatCount:1,rows:[]}]}
 const detail: AdminEventDetail={dateRange:'',publishedAt:null,publishedBy:null,readiness:{eventId:'e',status:'DRAFT',publishable:false,venue,sessionCount:1,expectedSessionSeatCount:1,sessions:[],issues:[]},id:'e',name:'E',description:'',category:'C',coverUrl:'',venueId:'v',status:'DRAFT',salesStartsAt:'2026-01-01T00:00:00Z',salesEndsAt:'2027-01-01T00:00:00Z',venue,
 sessions:[{id:'s',status:'DRAFT',venueId:'v',hallName:'H',startTime:'2026-12-01T00:00:00Z',gateTime:'2026-11-30T23:00:00Z',prices:[{zoneId:'z',price:150}]}]}
 vi.spyOn(adminApi,'venues').mockResolvedValue([venue]);vi.spyOn(adminApi,'event').mockResolvedValue(detail)
 const save=vi.spyOn(adminApi,'prices').mockImplementation(async(_e,_s,prices)=>({...detail,sessions:[{...detail.sessions[0]!,prices}]}))
 const w=mount(Page,{global:{plugins:[router]}});await flushPromises()
 const input=w.get('input[inputmode="decimal"]')
 const button=w.findAll('button').find(b=>b.text()==='保存区域票价')!
 expect((input.element as HTMLInputElement).value).toBe('1.50')
 for(const value of ['1.005','1.999','0.009','0','-1','1e2','1,000','','90071992547409.92']){
  await input.setValue(value);await button.trigger('click');await flushPromises();expect(save).not.toHaveBeenCalled();expect(w.get('[role="alert"]').text()).toMatch(/金额|票价/)
 }
 await input.setValue('90071992547409.91');await button.trigger('click');await flushPromises()
 expect(save).toHaveBeenLastCalledWith('e','s',[{zoneId:'z',price:Number.MAX_SAFE_INTEGER}])
 expect((input.element as HTMLInputElement).value).toBe('90071992547409.91')
 await button.trigger('click');await flushPromises();expect(save).toHaveBeenLastCalledWith('e','s',[{zoneId:'z',price:Number.MAX_SAFE_INTEGER}])
})
