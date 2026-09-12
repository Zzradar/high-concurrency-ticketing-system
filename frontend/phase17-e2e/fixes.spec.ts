import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'

async function login(page:Page, navigate=true) {
 if(navigate) await page.goto('/login')
 await page.getByLabel('用户名').fill('admin')
 await page.getByLabel('密码',{exact:true}).fill('Ticketing123!')
 await page.getByRole('button',{name:'登录',exact:true}).click()
 await expect(page).toHaveURL(/\/events$/)
 await expect(page.getByRole('button',{name:'账户菜单'})).toBeVisible()
}
async function state(page:Page) {
 return page.evaluate(async()=>{
  const app=(document.querySelector('#app') as unknown as {__vue_app__:{config:{globalProperties:{$router:{currentRoute:{value:{fullPath:string}}}}}}}).__vue_app__
  const modulePath='/src/auth/authState.ts';const {authState}=await import(modulePath)
  return {currentUser:authState.currentUser.value?.id??null,url:location.href,route:app.config.globalProperties.$router.currentRoute.value.fullPath,login:!!document.querySelector('input[autocomplete="username"]'),account:!!document.querySelector('[aria-label="账户菜单"]')}
 })
}
for(const path of ['/events','/admin/events']) for(const mode of ['success','401','timeout','network']) {
 test(`logout ${mode} from ${path}, no reload and re-login`,async({page},info)=>{
  const errors:string[]=[];const consoleErrors:string[]=[];page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});page.on('pageerror',e=>errors.push(e.message))
  await login(page);if(path!=='/events')await page.goto(path)
  let logoutStatus:number|string='not requested';let meCalls=0
  page.on('response',r=>{if(r.url().endsWith('/auth/logout'))logoutStatus=r.status()})
  page.on('request',r=>{if(r.url().endsWith('/auth/me'))meCalls++})
  if(mode!=='success')await page.route('**/api/auth/logout',async route=>{
   if(mode==='401')await route.fulfill({status:401,json:{code:'UNAUTHENTICATED',message:'expired'}})
   if(mode==='network'){logoutStatus='network abort';await route.abort('failed')}
   if(mode==='timeout'){logoutStatus='client timeout after 8000ms';await new Promise(r=>setTimeout(r,8500));await route.abort().catch(()=>{})}
  })
  await page.evaluate(()=>{(window as unknown as {noReloadMarker:string}).noReloadMarker='same document'})
  await page.getByRole('button',{name:'账户菜单'}).click()
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await expect(page).toHaveURL(/\/login$/,{timeout:12000})
  await expect(page.getByLabel('用户名')).toBeVisible()
  if(['timeout','network'].includes(mode))await expect(page.getByRole('status')).toContainText('退出请求未确认')
  expect(await page.evaluate(()=>(window as unknown as {noReloadMarker:string}).noReloadMarker)).toBe('same document')
  const afterLogout=await state(page)
  expect(afterLogout.currentUser).toBeNull();expect(afterLogout.route).toBe('/login');expect(afterLogout.account).toBe(false);expect(meCalls).toBe(0)
  await page.getByRole('link',{name:'登录',exact:true}).click()
  await expect(page.getByLabel('用户名')).toBeVisible()
  await page.unroute('**/api/auth/logout');await login(page,false)
  expect(errors).toEqual([])
  await info.attach('logout-evidence',{body:JSON.stringify({mode,path,logoutStatus,afterLogout,afterLogin:await state(page),meCalls,errors,consoleErrors}),contentType:'application/json'})
 })
}
for(const mode of ['missing','empty','invalid','valid'])test(`salesWindow ${mode}: recoverable page and auth navigation`,async({page},info)=>{
 const errors:string[]=[];const consoleErrors:string[]=[];page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});page.on('pageerror',e=>errors.push(e.message))
 await login(page)
 await page.route('**/api/events',async route=>{
  const response=await route.fetch();const data=await response.json()
  for(const event of data){if(mode==='missing')delete event.salesWindow;if(mode==='empty')event.salesWindow={};if(mode==='invalid')event.salesWindow.startsAt='invalid'}
  await route.fulfill({response,json:data})
 })
 await page.goto('/events')
 if(mode==='valid')await expect(page.locator('.event-card').first()).toBeVisible()
 else {await expect(page.getByRole('heading',{name:'活动加载失败'})).toBeVisible();await expect(page.locator('.event-card')).toHaveCount(0)}
 await page.getByRole('button',{name:'账户菜单'}).click();await page.getByRole('button',{name:'退出登录',exact:true}).click()
 await expect(page.getByLabel('用户名')).toBeVisible();await page.getByRole('link',{name:'登录',exact:true}).click();await login(page,false)
 if(mode!=='valid') {
  await expect(page.getByRole('heading',{name:'活动加载失败'})).toBeVisible()
  await page.unroute('**/api/events');await page.getByRole('button',{name:'重新加载'}).click();await expect(page.locator('.event-card').first()).toBeVisible()
 }
 expect(errors).toEqual([]);await info.attach('contract-evidence',{body:JSON.stringify({mode,state:await state(page),errors,consoleErrors}),contentType:'application/json'})
})
test('price validation prevents writes and stores exact cents with lossless roundtrip',async({page},info)=>{
 await login(page)
 const csrf=(await page.context().cookies()).find(c=>c.name==='ticketing_csrf')!.value
 const headers={'X-CSRF-Token':csrf,Origin:'http://127.0.0.1:5189'}
 const post=async(path:string,data:unknown)=>{const response=await page.request.post('/api'+path,{data,headers});expect(response.ok()).toBe(true);return response.json()}
 const venue=await post('/admin/venues',{name:'Exact price '+Date.now(),city:'成都',zones:[{code:'Z',name:'内场',rows:[{label:'A',seatCount:2}]}]})
 const time=(h:number)=>new Date(Date.now()+h*3600000).toISOString()
 const event=await post('/admin/events',{name:'Exact price',description:'',category:'演唱会',coverUrl:'/images/concert-cover.png',venueId:venue.id,salesStartsAt:time(-1),salesEndsAt:time(24)})
 const detail=await post('/admin/events/'+event.id+'/sessions',{hallName:'H',startTime:time(12),gateTime:time(10)})
 const sid=detail.sessions[0].id;let writes=0
 page.on('request',r=>{if(r.method()==='PUT'&&r.url().endsWith('/prices'))writes++})
 await page.goto('/admin/events/'+event.id)
 const field=page.getByLabel('内场 票价（元）'),save=page.getByRole('button',{name:'保存区域票价'})
 for(const value of ['1.005','1.999','0.009','0','-1','1e2','1,000','','90071992547409.92']){
  await field.fill(value);await save.click();await expect(page.getByRole('alert')).toContainText('票价');expect(writes).toBe(0)
 }
 const evidence=[]
 for(const [yuan,fen,display] of [['1',100,'1.00'],['1.5',150,'1.50'],['0.01',1,'0.01'],['90071992547409.91',Number.MAX_SAFE_INTEGER,'90071992547409.91']] as const){
  await field.fill(yuan);await save.click();await expect(page.getByRole('status')).toContainText('区域票价已保存');await expect(field).toHaveValue(display)
  const query=`SELECT price FROM session_zone_prices WHERE session_id='${sid}' AND zone_id='${venue.zones[0].id}';`
  const stored=execFileSync('docker',['exec','-i',process.env.PHASE17_POSTGRES_CONTAINER||'p17-fix-pg','psql','-U','postgres','-qAt','-c',query],{encoding:'utf8'}).trim()
  expect(stored).toBe(String(fen));await save.click();await expect(page.getByRole('status')).toContainText('区域票价已保存')
  const roundtrip=await(await page.request.get('/api/admin/events/'+event.id)).json();expect(roundtrip.sessions[0].prices[0].price).toBe(fen)
  evidence.push({yuan,fen,display,stored})
 }
 await info.attach('price-evidence',{body:JSON.stringify({writes,evidence}),contentType:'application/json'})
})
