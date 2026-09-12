import {describe,it,expect} from 'vitest'
import {requireAdmissionPolicy} from './admissionPolicyContract'
const off={eventId:'e',mode:'OFF',policyVersion:0,prequeueSeconds:null,maxActiveUsers:null,admissionRatePerSecond:null,leaseSeconds:null,queueGeneration:null}
const active={...off,mode:'ENFORCED',policyVersion:1,prequeueSeconds:0,maxActiveUsers:1,admissionRatePerSecond:1,leaseSeconds:10,queueGeneration:'a'.repeat(32)}
describe('Admin admission policy runtime contract',()=>{
 it('accepts synthetic OFF and all persisted modes',()=>{
  expect(requireAdmissionPolicy(off,'e')).toEqual(off)
  for(const mode of ['OFF','OBSERVE','PAUSED','ENFORCED'])expect(requireAdmissionPolicy({...active,mode},'e').mode).toBe(mode)
 })
 it('rejects coercion, wrong identity, missing nullable fields and unsafe numbers',()=>{
  for(const value of [null,[],{...off,eventId:'another'},{...off,queueGeneration:undefined},{...active,policyVersion:'1'},{...active,mode:['ENFORCED']},{...active,maxActiveUsers:[1]},{...active,leaseSeconds:9},{...active,policyVersion:Number.MAX_SAFE_INTEGER+1},{...active,queueGeneration:'not-a-generation'}])expect(()=>requireAdmissionPolicy(value,'e')).toThrow('请重新加载')
 })
})
