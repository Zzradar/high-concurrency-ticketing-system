import {describe,it,expect,vi,afterEach} from 'vitest'
import {createMemoryHistory} from 'vue-router'
import {createAppRouter} from './router'
import {authState} from './auth/authState'
import {adminApi} from './api/adminApi'
import {http} from './api/ticketApi'
afterEach(()=>vi.restoreAllMocks())
describe('admin permissions and shared transport',()=>{
 it('redirects anonymous to login and CUSTOMER to events',async()=>{for(const role of [null,'CUSTOMER'] as const){vi.spyOn(authState,'ensureAuthLoaded').mockResolvedValue(role?{id:'u',username:'u',displayName:'U',role}:null);const router=createAppRouter(createMemoryHistory());await router.push('/admin/venues/new');expect(router.currentRoute.value.path).toBe(role?'/events':'/login')}})
 it('allows ADMIN routes with both required guards',async()=>{vi.spyOn(authState,'ensureAuthLoaded').mockResolvedValue({id:'a',username:'a',displayName:'A',role:'ADMIN'});const router=createAppRouter(createMemoryHistory());await router.push('/admin/events/new');expect(router.currentRoute.value.meta.requiresAdmin).toBe(true);expect(router.currentRoute.value.meta.requiresAuth).toBe(true);expect(router.currentRoute.value.path).toBe('/admin/events/new')})
 it('sends admin writes through the same cookie/CSRF client',async()=>{const post=vi.spyOn(http,'post').mockResolvedValue({data:{disposition:'PUBLISHED_NOW'}});expect((await adminApi.publish('E1')).disposition).toBe('PUBLISHED_NOW');expect(post).toHaveBeenCalledWith('/admin/events/E1/publish',undefined,{timeout:30000});expect(http.defaults.withCredentials).toBe(true)})
})
