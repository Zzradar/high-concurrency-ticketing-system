import {test,expect} from '@playwright/test'
import {readFileSync,writeFileSync} from 'node:fs'
import {resolve} from 'node:path'
const dir=resolve(process.cwd(),'../performance/experiments/phase17-admin-publishing')
const scales=JSON.parse(readFileSync(resolve(dir,'scale.json'),'utf8')) as {seatCount:number;sessionId:string}[]
for(const scale of scales)test(`renders only current Zone for ${scale.seatCount} seats`,async({page})=>{
 const samples=[]
 for(let i=0;i<5;i++){const start=Date.now();await page.goto('/sessions/'+scale.sessionId+'/seats');await expect(page.locator('.seat-item')).toHaveCount(scale.seatCount/5);await expect(page.locator('.seat-item').first()).toBeVisible();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));samples.push(Date.now()-start)}
 await page.getByRole('button',{name:/Zone 1 /}).click();await expect(page.locator('.seat-item')).toHaveCount(scale.seatCount/5)
 writeFileSync(resolve(dir,`browser-${scale.seatCount}.json`),JSON.stringify({seatCount:scale.seatCount,currentZoneDomSeats:scale.seatCount/5,n:5,navigationToPaintMs:samples,p50Ms:[...samples].sort((a,b)=>a-b)[2],p95Ms:Math.max(...samples)},null,2))
})
