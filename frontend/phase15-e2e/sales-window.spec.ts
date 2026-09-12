import { test, expect, type BrowserContext } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
const root=resolve(process.cwd(),'..'), session='ses-concert-1001', event='evt-concert-2026'
const python = (source: string) => execFileSync('python',['-c',"import sys;sys.path.insert(0,'backend/tests');from phase15_test_support import *;"+source],{cwd:root,encoding:'utf8'}).trim()
const sql = (query: string) => python('print(sql('+JSON.stringify(query)+'))')
const window = (start: number,end: number) => sql(`UPDATE events SET sales_starts_at=clock_timestamp()+make_interval(secs=>${start}),sales_ends_at=clock_timestamp()+make_interval(secs=>${end}) WHERE id='${event}';`)
let user: string, original: string
async function mutation(context: BrowserContext,path: string,data?: unknown) {
  const cookies=await context.cookies();const csrf=cookies.find(c=>c.name==='ticketing_csrf')!.value
  return context.request.post('/api'+path,{data,headers:{Origin:'http://127.0.0.1:5177','X-CSRF-Token':csrf}})
}
test.beforeEach(async ({context}) => {
  original=sql(`SELECT sales_starts_at||'|'||sales_ends_at FROM events WHERE id='${event}';`)
  user=python("u,c=client();print(username_for_user(u))")
  const response=await context.request.post('/api/auth/login',{data:{username:user,password:process.env.PHASE15_TEST_PASSWORD},headers:{Origin:'http://127.0.0.1:5177'}})
  expect(response.status()).toBe(200)
})
test.afterEach(async ({context}) => {
  const orders=await context.request.get('/api/orders?sessionId='+session)
  for (const order of await orders.json()) {
    if(order.status==='PENDING_PAYMENT') await mutation(context,'/orders/'+order.id+'/cancel')
    if(order.status==='PAID') {
      const refund=await mutation(context,'/orders/'+order.id+'/refunds')
      expect([200,201,202]).toContain(refund.status())
      await expect.poll(async () => (await (await context.request.get('/api/orders/'+order.id)).json()).status,{timeout:15000}).toBe('CANCELLED')
    }
  }
  const checkouts=await context.request.get('/api/checkout-sessions?sessionId='+session+'&recoverable=true')
  for (const checkout of await checkouts.json()) if(checkout.status==='SELECTING') await mutation(context,'/checkout-sessions/'+checkout.id+'/abandon')
  const [start,end]=original.split('|');sql(`UPDATE events SET sales_starts_at='${start}',sales_ends_at='${end}' WHERE id='${event}';`)
})
test('NOT_STARTED to OPEN, existing order still pays after ENDED',async({page,context},info)=>{
  window(5,18)
  let availability=0;page.on('request',r=>{if(r.url().includes('/seat-availability?'))availability++})
  await page.goto('/sessions/'+session+'/seats')
  const seat=page.getByRole('button',{name:/^A01，可选/})
  await expect(seat).toBeDisabled();await expect(page.locator('.seat-grid')).toBeVisible()
  const first=availability;await page.waitForTimeout(2200);expect(availability).toBe(first)
  await expect(seat).toBeEnabled({timeout:8000});await seat.click()
  await expect(page.getByRole('button',{name:'提交预订',exact:true})).toBeEnabled()
  await page.getByRole('button',{name:'提交预订',exact:true}).click();await page.waitForURL(/\/orders\//)
  await expect.poll(async()=> (await (await context.request.get('/api/sessions/'+session)).json()).salesWindow.state,{timeout:20000}).toBe('ENDED')
  await page.getByRole('button',{name:/模拟支付/}).click()
  await expect(page.getByRole('button',{name:'申请全额退款',exact:true})).toBeVisible({timeout:15000})
  await page.screenshot({path:resolve(root,'performance/experiments/phase15-sales-window/paid-after-end.png'),fullPage:true})
  await info.attach('window-and-payment',{body:JSON.stringify({initialSnapshots:first,paidAfterEnd:true}),contentType:'application/json'})
})
test('OPEN to ENDED stops Delta and closes an unconfirmed SELECTING session',async({page,context})=>{
  window(-100,7)
  const created=await mutation(context,'/checkout-sessions',{sessionId:session,seatIds:[session+'-A01']});expect(created.status()).toBe(201)
  const checkout=await created.json()
  const identity=await (await context.request.get('/api/auth/me')).json()
  await page.addInitScript(({key,checkout})=>sessionStorage.setItem(key,JSON.stringify({checkoutSessionId:checkout.id,sessionId:checkout.sessionId})),{key:'ticketing.checkout.'+identity.id,checkout})
  let availability=0;page.on('request',r=>{if(r.url().includes('/seat-availability?'))availability++})
  await page.goto('/sessions/'+session+'/seats');await expect(page.getByRole('button',{name:'移除座位 A01',exact:true})).toBeVisible()
  await expect(page.getByText('售票已结束。',{exact:false})).toHaveCount(0)
  await expect(page.locator('.message-banner').filter({hasText:'售票已结束'})).toBeVisible({timeout:10000})
  await expect(page.getByRole('button',{name:'提交预订',exact:true})).toBeDisabled()
  const stopped=availability;await page.waitForTimeout(4500);expect(availability).toBe(stopped)
  const rejected=await mutation(context,'/checkout-sessions/'+checkout.id+'/confirm');expect(rejected.status()).toBe(409);expect((await rejected.json()).code).toBe('SALES_ENDED')
  expect((await (await context.request.get('/api/checkout-sessions/'+checkout.id)).json()).status).toBe('ABANDONED')
})

test('ENDED page recovers a SUBMITTING session with an already committed order',async({page,context})=>{
  window(-100,300)
  const created=await mutation(context,'/checkout-sessions',{sessionId:session,seatIds:[session+'-A01']});expect(created.status()).toBe(201)
  const checkout=await created.json(), identity=await (await context.request.get('/api/auth/me')).json()
  const key='p15-browser-'+checkout.id
  sql(`UPDATE checkout_sessions SET status='SUBMITTING',active_confirm_idempotency_key='${key}' WHERE id='${checkout.id}';`)
  const csrf=(await context.cookies()).find(c=>c.name==='ticketing_csrf')!.value
  const response=await context.request.post('/api/reservations',{data:{sessionId:session,seatIds:checkout.seatIds},headers:{Origin:'http://127.0.0.1:5177','X-CSRF-Token':csrf,'Idempotency-Key':key}})
  expect(response.status()).toBe(201);const formal=await response.json()
  window(-100,-1)
  await page.addInitScript(({key,checkout})=>sessionStorage.setItem(key,JSON.stringify({checkoutSessionId:checkout.id,sessionId:checkout.sessionId})),{key:'ticketing.checkout.'+identity.id,checkout})
  await page.goto('/sessions/'+session+'/seats')
  await page.waitForURL('**/orders/'+formal.order.id)
  expect(sql(`SELECT count(*) FROM orders WHERE user_id='${identity.id}';`)).toBe('1')
})
