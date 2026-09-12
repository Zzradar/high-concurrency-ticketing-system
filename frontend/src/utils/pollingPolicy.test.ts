import { describe,it,expect } from 'vitest'
import { nextPollDelay,retryHint,validPollHint } from './pollingPolicy'
import { isAvailabilitySync } from './availabilityContract'
describe('bounded server-directed polling',()=>{
 it('keeps the old 2s fast and 5s empty floors and backs off consecutive empty responses',()=>{
  expect(nextPollDelay({pollAfterMs:2000,emptyStreak:0,errorStreak:0},()=>.5)).toBe(2000)
  expect(nextPollDelay({pollAfterMs:5000,emptyStreak:1,errorStreak:0},()=>.5)).toBe(5000)
  expect(nextPollDelay({pollAfterMs:5000,emptyStreak:3,errorStreak:0},()=>.5)).toBe(20000)
  expect(nextPollDelay({pollAfterMs:2000,emptyStreak:0,errorStreak:0},()=>.5)).toBe(2000)
 })
 it('drains hasMore, bounds jitter and honors 429/503 retry minimums',()=>{
  expect(nextPollDelay({hasMore:true,emptyStreak:5,errorStreak:0},()=>1)).toBe(0)
  const input={pollAfterMs:5000,emptyStreak:2,errorStreak:0}
  expect(nextPollDelay(input,()=>0)).toBe(8000);expect(nextPollDelay(input,()=>1)).toBe(12000)
  for(const errorStreak of [1,2,5])expect(nextPollDelay({pollAfterMs:2000,emptyStreak:0,errorStreak,retryAfterMs:20000},()=>0)).toBeGreaterThanOrEqual(20000)
  expect(nextPollDelay({pollAfterMs:30000,emptyStreak:100,errorStreak:100},()=>1)).toBe(30000)
 })
 it('rejects coerced, fractional, nonfinite and out-of-range numeric hints',()=>{
  for(const value of ['2000',true,[],{},null,NaN,Infinity,-1,1.5,30001])expect(validPollHint(value)).toBe(false)
  expect(validPollHint(0,true)).toBe(true);expect(validPollHint(0)).toBe(false)
  expect(retryHint('2000','2',0)).toBe(2000)
  expect(retryHint(1000,'Thu, 01 Jan 1970 00:00:05 GMT',0)).toBe(5000)
  expect(retryHint(undefined,'999999999999999999999',0)).toBe(30000)
  expect(retryHint(undefined,'garbage')).toBeUndefined()
 })
 it('validates the complete availability runtime contract before applying it',()=>{
  const base={sessionId:'S',zone:'Z',mode:'snapshot',generation:'g',cursor:'1-0',reset:false,degraded:false,hasMore:false,pollAfterMs:2000,seats:[],zones:[{zone:'Z',total:0,available:0,held:0,sold:0}]}
  expect(isAvailabilitySync(base)).toBe(true)
  for(const pollAfterMs of ['2000',true,[],null,NaN,2000.5,0,30001])expect(isAvailabilitySync({...base,pollAfterMs})).toBe(false)
  expect(isAvailabilitySync({...base,zones:[{zone:'Z',total:'0',available:0,held:0,sold:0}]})).toBe(false)
  expect(isAvailabilitySync({...base,degraded:true})).toBe(false)
 })
})
