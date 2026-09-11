import { test, expect, type BrowserContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
const root=resolve(process.cwd(),'..')
const session='perf-session-phase16'
const url='/sessions/'+session+'/seats'
const seatId='perf-ss-phase16-00001'
async function login(context: BrowserContext, username: string) {
  const result=await context.request.post('/api/auth/login',{data:{username,password:process.env.PHASE16_TEST_PASSWORD},headers:{Origin:'http://127.0.0.1:5176'}})
  expect(result.status()).toBe(200)
}
function seat(page: Page,status: string,label='P00001') {return page.getByRole('button',{name:label+'，'+status+'，¥100',exact:true})}
function delta(page: Page,status: string) {
  return page.waitForResponse(async r=>{
    if(!r.url().includes('/seat-availability?') || r.status()!==200)return false
    const body=await r.json()
    return body.mode==='delta' && body.changes.some((s:{id:string;status:string})=>s.id===seatId && s.status===status)
  })
}
test.beforeEach(() => {
  const cleanup="import sys;sys.path.insert(0,'backend/tests');from auth_test_support import AuthenticatedClient;import auth_test_support;auth_test_support.BASE_URL='http://127.0.0.1:18096';clients=[AuthenticatedClient('it-perf-user-160001'),AuthenticatedClient('it-perf-user-160002')];[(c.request('/checkout-sessions/'+x['id']+'/abandon',method='POST')) for c in clients for x in c.request('/checkout-sessions?sessionId=perf-session-phase16&recoverable=true')[1]]"
  execFileSync('python',['-c',cleanup],{cwd:root})
})
test('5000 layout, Zone switching, two-user Delta, Confirm, payment and buyer refund',async({browser},testInfo)=>{
  const ca=await browser.newContext({baseURL:'http://127.0.0.1:5176'}),cb=await browser.newContext({baseURL:'http://127.0.0.1:5176'})
  await login(ca,'it-perf-user-160001');await login(cb,'it-perf-user-160002')
  const a=await ca.newPage(),b=await cb.newPage()
  const syncs: {mode:string;changes:number;zone:string}[]=[]
  b.on('response',async r=>{if(r.url().includes('/seat-availability?')&&r.status()===200){const v=await r.json();syncs.push({mode:v.mode,changes:v.changes?.length??0,zone:v.zone})}})
  await a.goto(url);await b.goto(url)
  await expect(seat(a,'可选')).toBeVisible();await expect(seat(b,'可选')).toBeVisible()
  expect((await (await ca.request.get('/api/sessions/'+session+'/seat-layout')).json()).seats).toHaveLength(5000)
  await expect(a.locator('.seat-item')).toHaveCount(1000)
  await a.getByRole('button',{name:/Zone 1 /}).click()
  await expect(a.getByRole('button',{name:'P01001，可选，¥100',exact:true})).toBeVisible()
  await a.getByRole('button',{name:/Zone 0 /}).click()
  const held=delta(b,'HELD')
  await seat(a,'可选').click();await expect(a.getByRole('button',{name:'移除座位 P00001',exact:true})).toBeVisible()
  await b.bringToFront();await held;await expect(seat(b,'锁定中')).toBeDisabled()
  await expect(seat(a,'已选择')).toHaveClass(/seat-item--available/)
  // Cross-Zone selected labels remain available while only one Zone grid is rendered.
  await a.bringToFront();await a.getByRole('button',{name:/Zone 1 /}).click()
  await expect(a.getByRole('button',{name:'移除座位 P00001',exact:true})).toBeVisible()
  await a.getByRole('button',{name:/Zone 0 /}).click()
  const released=delta(b,'AVAILABLE')
  await a.getByRole('button',{name:'移除座位 P00001',exact:true}).click()
  await b.bringToFront();await released;await expect(seat(b,'可选')).toBeEnabled()
  await a.bringToFront();await seat(a,'可选').click()
  await expect(a.getByRole('button',{name:'提交预订',exact:true})).toBeEnabled()
  await b.bringToFront();await expect(seat(b,'锁定中')).toBeDisabled()
  const formalHeld=delta(b,'HELD')
  await a.bringToFront();await a.getByRole('button',{name:'提交预订',exact:true}).click()
  await a.waitForURL(/\/orders\//);await b.bringToFront();await formalHeld
  const sold=delta(b,'SOLD')
  await a.bringToFront();await a.getByRole('button',{name:/模拟支付/}).click()
  await b.bringToFront();await sold;await expect(seat(b,'已售')).toBeDisabled()
  await a.bringToFront();await expect(a.getByRole('button',{name:'申请全额退款',exact:true})).toBeVisible({timeout:20000})
  const refunded=delta(b,'AVAILABLE')
  await a.getByRole('button',{name:'申请全额退款',exact:true}).click();await a.getByRole('button',{name:'确认退款',exact:true}).click()
  await b.bringToFront();await refunded;await expect(seat(b,'可选')).toBeEnabled()
  expect(syncs.filter(s=>s.mode==='delta'&&s.changes>0).length).toBeGreaterThanOrEqual(5)
  await b.screenshot({path:resolve(root,'performance/experiments/phase16-availability/browser-zone.png'),fullPage:true})
  await testInfo.attach('delta-observations',{body:JSON.stringify(syncs),contentType:'application/json'})
  await ca.close();await cb.close()
})

test('short TTL and formal cancellation release appear through Delta without reload',async({browser})=>{
  const context=await browser.newContext({baseURL:'http://127.0.0.1:5176'});await login(context,'it-perf-user-160002')
  const page=await context.newPage();await page.goto(url);await expect(seat(page,'可选')).toBeVisible()
  const python="import os,sys;sys.path.insert(0,'backend/tests');os.environ['PHASE16_REDIS_CONTAINER']='phase16-api-redis';from phase16_read_model_test import ReadModelTest;t=ReadModelTest();t.session='perf-session-phase16';t.prefix='ticketing:seat-availability:{perf-session-phase16}';t.hold('Ensure',['perf-ss-phase16-00001'],'phase16-short-ttl',1,2)"
  execFileSync('python',['-c',python],{cwd:root})
  const held=delta(page,'HELD');await page.getByRole('button',{name:'刷新座位状态',exact:true}).click();await held
  const expired=delta(page,'AVAILABLE');await expired;await expect(seat(page,'可选')).toBeEnabled()
  await seat(page,'可选').click();await page.getByRole('button',{name:'提交预订',exact:true}).click();await page.waitForURL(/\/orders\//)
  const observer=await browser.newPage({baseURL:'http://127.0.0.1:5176'});await observer.goto(url);await expect(seat(observer,'锁定中')).toBeDisabled()
  const cancelled=delta(observer,'AVAILABLE');await page.bringToFront();await page.getByRole('button',{name:'取消订单',exact:true}).click()
  await observer.bringToFront();await cancelled;await expect(seat(observer,'可选')).toBeEnabled()
  await observer.close();await context.close()
})
