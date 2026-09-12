import {expect,it} from 'vitest'
import {admissionInteger} from './admissionPolicyInput'
it('retains raw input and rejects coercion, exponent, decimals and overflow',()=>{
 for(const raw of ['', ' ', ' 1','1 ', '1e2','1.0','01','-1','+1','1,000',true,1,[],null,undefined,'9007199254740992']) expect(()=>admissionInteger(raw,0,1000000)).toThrow()
 expect(admissionInteger('0',0,86400)).toBe(0)
 expect(admissionInteger('1000000',1,1000000)).toBe(1000000)
 expect(()=>admissionInteger('0',1,10)).toThrow()
 expect(()=>admissionInteger('11',1,10)).toThrow()
})
