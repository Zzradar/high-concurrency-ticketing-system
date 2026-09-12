import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import LoginView from './LoginView.vue'
afterEach(()=>vi.unstubAllEnvs())
for(const [dev,demo,shown] of [[false,'false',false],[false,'true',true],[true,'false',true]] as const)
 it(`demo credentials dev=${dev}, demo=${demo}`,async()=>{
  vi.stubEnv('DEV',dev);vi.stubEnv('VITE_USE_MOCK_API',demo)
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/login',component:LoginView}]});await router.push('/login')
  const w=mount(LoginView,{global:{plugins:[router]}});expect(w.text().includes('开发演示账号')).toBe(shown);w.unmount()
 })
