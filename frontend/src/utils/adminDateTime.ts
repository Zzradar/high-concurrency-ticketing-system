export function toBeijingInput(iso:string):string {
 if(!iso)return ''
 const date=new Date(iso)
 if(!Number.isFinite(date.getTime()))throw new Error('无效日期')
 return new Date(date.getTime()+8*3600000).toISOString().slice(0,16)
}
export function fromBeijingInput(value:string):string {
 if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))throw new Error('请填写有效的北京时间')
 const date=new Date(value+':00+08:00')
 if(!Number.isFinite(date.getTime()) || toBeijingInput(date.toISOString())!==value)throw new Error('请填写有效的北京时间')
 return date.toISOString()
}
export function consecutiveRows(start:string,count:number,seats:number) {
 if(!/^[A-Z]{1,3}$/.test(start)||!Number.isInteger(count)||count<1||count>200||!Number.isInteger(seats)||seats<1||seats>500)throw new Error('连续行参数无效')
 let first=0;for(const c of start)first=first*26+c.charCodeAt(0)-64
 return Array.from({length:count},(_,i)=>{let n=first+i,label='';while(n){n--;label=String.fromCharCode(65+n%26)+label;n=Math.floor(n/26)}return {label,seatCount:seats}})
}
