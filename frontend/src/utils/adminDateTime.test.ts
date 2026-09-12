import {describe,it,expect} from 'vitest'
import {fromBeijingInput,toBeijingInput,consecutiveRows} from './adminDateTime'
describe('admin Beijing timestamps',()=>{
 it('uses +08 regardless of host timezone',()=>{expect(fromBeijingInput('2026-10-08T19:30')).toBe('2026-10-08T11:30:00.000Z');expect(toBeijingInput('2026-10-08T23:30:00Z')).toBe('2026-10-09T07:30')})
 it('rejects invalid calendar dates and missing inputs',()=>{for(const s of ['','2026-02-30T12:00','2026-10-01T24:00','2026-1-1T00:00'])expect(()=>fromBeijingInput(s)).toThrow()})
 it('expands consecutive rows across Z with explicit counts',()=>{expect(consecutiveRows('Z',3,50)).toEqual([{label:'Z',seatCount:50},{label:'AA',seatCount:50},{label:'AB',seatCount:50}]);expect(()=>consecutiveRows('A',201,1)).toThrow()})
})
