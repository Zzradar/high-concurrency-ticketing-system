import {test,expect,type Page} from '@playwright/test'
import {resolve} from 'node:path'
const root=resolve(process.cwd(),'..')
const time=(days:number,hour:number)=>{const d=new Date(Date.now()+days*86400000);return d.toISOString().slice(0,10)+'T'+String(hour).padStart(2,'0')+':00'}
async function login(page:Page,user:string){await page.goto('/login');await page.getByLabel('用户名').fill(user);await page.getByLabel('密码',{exact:true}).fill('Ticketing123!');await page.getByRole('button',{name:'登录',exact:true}).click();await page.waitForURL('**/events')}
async function create(page:Page,publish=true){
 const name='浏览器活动 '+Date.now();await page.goto('/admin/venues/new');await page.getByLabel('场馆名称').fill(name+'场馆');await page.getByLabel('城市',{exact:true}).fill('成都');await page.getByLabel('连续行数量').fill('1');await page.getByLabel('每行座位数').fill('3')
 for(const z of ['内场','看台']){await page.getByRole('button',{name:'添加区域',exact:true}).click();const box=page.locator('[data-testid^="zone-"]').last();await box.getByLabel('区域名称').fill(z);await box.getByRole('button',{name:'添加连续行'}).click()}
 await page.getByRole('button',{name:'保存场馆',exact:true}).click();await expect(page.getByRole('status')).toContainText('场馆已保存');await page.waitForURL(/\/admin\/venues\/VEN-/);const vid=page.url().split('/').pop()!
 await page.goto('/admin/events/new');await page.getByLabel('活动名称',{exact:true}).fill(name);await page.getByLabel('场馆',{exact:true}).selectOption(vid);await page.getByLabel('开售时间（北京时间）',{exact:true}).fill(time(-1,8));await page.getByLabel('停售时间（北京时间）',{exact:true}).fill(time(3,22));await page.getByRole('button',{name:'保存活动草稿'}).click();await expect(page.getByRole('status')).toContainText('活动已保存');const eid=page.url().split('/').pop()!
 await page.getByLabel('开始时间（北京时间）',{exact:true}).fill(time(2,19));await page.getByLabel('入场时间（北京时间）',{exact:true}).fill(time(2,17));await page.getByRole('button',{name:'添加场次',exact:true}).click();await expect(page.getByRole('status')).toContainText('场次已保存')
 await page.getByLabel('内场 票价（元）').fill('100');await page.getByLabel('看台 票价（元）').fill('200');await page.getByRole('button',{name:'保存区域票价'}).click();await expect(page.getByRole('status')).toContainText('区域票价已保存');await page.getByRole('button',{name:'刷新发布预览'}).click();await expect(page.getByRole('button',{name:'确认发布',exact:true})).toBeEnabled()
 const detail=await (await page.request.get('/api/admin/events/'+eid)).json();const sid=detail.sessions[0].id
 if(publish){await page.getByRole('button',{name:'确认发布',exact:true}).click();await expect(page.getByRole('status')).toContainText('发布成功')}
 return {eid,sid,vid,name}
}
test('ADMIN creates and publishes in UI; CUSTOMER sees ordered Zones without restart',async({page,browser})=>{
 await login(page,'admin');await page.getByRole('button',{name:'账户菜单'}).click();await expect(page.getByRole('link',{name:'管理后台',exact:true})).toBeVisible();const data=await create(page)
 const context=await browser.newContext({baseURL:'http://127.0.0.1:5177'}),buyer=await context.newPage();await login(buyer,'demo');await expect(buyer.getByText(data.name,{exact:true})).toBeVisible();await buyer.goto('/sessions/'+data.sid+'/seats');await expect(buyer.locator('.seat-item')).toHaveCount(3);await expect(buyer.getByRole('button',{name:/内场 /})).toBeVisible();await buyer.getByRole('button',{name:/看台 /}).click();await expect(buyer.getByRole('button',{name:'A001，可选，¥200',exact:true})).toBeVisible()
 await page.screenshot({path:resolve(root,'performance/experiments/phase17-admin-publishing/admin-published.png'),fullPage:true});await context.close()
})
test('DRAFT is isolated; CUSTOMER cannot enter admin; ADMIN can continue editing',async({page,browser})=>{
 await login(page,'admin');const data=await create(page,false);const c=await browser.newContext({baseURL:'http://127.0.0.1:5177'}),buyer=await c.newPage();await login(buyer,'demo');await expect(buyer.getByText(data.name,{exact:true})).toHaveCount(0)
 for(const path of ['/events/'+data.eid,'/sessions/'+data.sid,'/sessions/'+data.sid+'/seat-layout'])expect((await buyer.request.get('/api'+path)).status()).toBe(404)
 await buyer.goto('/admin/events/'+data.eid);await expect(buyer).toHaveURL(/\/events$/);await page.getByLabel('活动介绍').fill('草稿仍可编辑');await page.getByRole('button',{name:'保存活动草稿'}).click();await expect(page.getByRole('status')).toContainText('活动已保存');await c.close()
})
test('dynamic published inventory completes hold, confirm, payment, refund and cancel',async({page,browser})=>{
 await login(page,'admin');const {sid}=await create(page);const c=await browser.newContext({baseURL:'http://127.0.0.1:5177'}),buyer=await c.newPage();await login(buyer,'demo');await buyer.goto('/sessions/'+sid+'/seats');const seat=buyer.getByRole('button',{name:'A001，可选，¥100',exact:true});await expect(seat).toBeVisible();await seat.click();await buyer.getByRole('button',{name:'提交预订',exact:true}).click();await buyer.waitForURL(/\/orders\//);const order=buyer.url().split('/').pop()!
 await buyer.getByRole('button',{name:/模拟支付/}).click();await expect(buyer.getByRole('button',{name:'申请全额退款',exact:true})).toBeVisible({timeout:25000});await buyer.getByRole('button',{name:'申请全额退款',exact:true}).click();await buyer.getByRole('button',{name:'确认退款',exact:true}).click();await expect.poll(async()=>{const o=await(await buyer.request.get('/api/orders/'+order)).json();return o.status},{timeout:20000}).toBe('CANCELLED')
 await c.close();const cancelContext=await browser.newContext({baseURL:'http://127.0.0.1:5177'});const cancelBuyer=await cancelContext.newPage();await login(cancelBuyer,'demo');await cancelBuyer.goto('/sessions/'+sid+'/seats');const cancelSeat=cancelBuyer.getByRole('button',{name:'A001，可选，¥100',exact:true});await expect(cancelSeat).toBeEnabled();await cancelSeat.click();await cancelBuyer.getByRole('button',{name:'提交预订',exact:true}).click();await cancelBuyer.waitForURL(/\/orders\//);await cancelBuyer.getByRole('button',{name:'取消订单',exact:true}).click();await expect.poll(async()=>{const snap=await(await cancelBuyer.request.get('/api/sessions/'+sid+'/seat-availability?zone='+encodeURIComponent('内场'))).json();return snap.seats.every((s:{status:string})=>s.status==='AVAILABLE')}).toBe(true)
 await cancelContext.close()
})
