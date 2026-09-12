import { http } from './ticketApi'
export interface AdminRow { label: string; seatCount: number }
export interface AdminZone { id: string; code: string; name: string; sortOrder: number; seatCount: number; rows: AdminRow[] }
export interface AdminVenueSummary { id: string; name: string; city: string; totalSeats: number; zoneCount: number; frozen: boolean }
export interface AdminVenueDetail extends AdminVenueSummary { zones: AdminZone[]; pricingReset?: boolean }
export interface VenuePlan { name: string; city: string; zones: { code: string; name: string; rows: AdminRow[] }[] }
export interface AdminZonePrice { zoneId: string; price: number }
export interface AdminSession { id: string; status: 'DRAFT'|'ON_SALE'|'SOLD_OUT'; venueId: string; hallName: string; startTime: string; gateTime: string; prices: AdminZonePrice[] }
export interface AdminEventSummary { id: string; name: string; status: 'DRAFT'|'ON_SALE'|'COMING_SOON'; venueId: string; venueName: string; sessionCount: number }
export interface EventInput { name: string; description: string; category: string; coverUrl: string; venueId: string; salesStartsAt: string; salesEndsAt: string }
export interface PublishPreview { eventId: string; status: string; publishable: boolean; venue: AdminVenueDetail; sessionCount: number; expectedSessionSeatCount: number; sessions: {id:string;startTime:string;configuredZones:number;requiredZones:number}[]; issues: {code:string;message:string;sessionId?:string;zoneId?:string}[] }
export interface AdminEventDetail extends Omit<AdminEventSummary, 'venueName'|'sessionCount'>, EventInput { dateRange: string; publishedAt: string|null; publishedBy: string|null; sessions: AdminSession[]; venue: AdminVenueDetail; readiness: PublishPreview; savedSessionId?: string }
export interface PublishResult { disposition: 'PUBLISHED_NOW'|'ALREADY_PUBLISHED'; event: AdminEventDetail; inventory: {sessionCount:number;seatCountPerSession:number;sessionSeatCount:number} }
const eventPath=(id:string)=>'/admin/events/'+encodeURIComponent(id)
export const adminApi={
 venues:async()=> (await http.get<AdminVenueSummary[]>('/admin/venues')).data,
 venue:async(id:string)=>(await http.get<AdminVenueDetail>('/admin/venues/'+encodeURIComponent(id))).data,
 saveVenue:async(id:string|undefined,body:VenuePlan)=>(await (id?http.put<AdminVenueDetail>('/admin/venues/'+encodeURIComponent(id),body):http.post<AdminVenueDetail>('/admin/venues',body))).data,
 events:async()=>(await http.get<AdminEventSummary[]>('/admin/events')).data,
 event:async(id:string)=>(await http.get<AdminEventDetail>(eventPath(id))).data,
 saveEvent:async(id:string|undefined,body:EventInput)=>(await (id?http.put<AdminEventDetail>(eventPath(id),body):http.post<AdminEventDetail>('/admin/events',body))).data,
 display:async(id:string,body:Pick<EventInput,'name'|'description'|'category'|'coverUrl'>)=>(await http.patch<AdminEventDetail>(eventPath(id)+'/display',body)).data,
 session:async(eid:string,sid:string|undefined,body:Pick<AdminSession,'hallName'|'startTime'|'gateTime'>)=>(await (sid?http.put<AdminEventDetail>(eventPath(eid)+'/sessions/'+sid,body):http.post<AdminEventDetail>(eventPath(eid)+'/sessions',body))).data,
 deleteSession:async(eid:string,sid:string)=>(await http.delete<AdminEventDetail>(eventPath(eid)+'/sessions/'+sid)).data,
 prices:async(eid:string,sid:string,prices:AdminZonePrice[])=>(await http.put<AdminEventDetail>(eventPath(eid)+'/sessions/'+sid+'/prices',{prices})).data,
 preview:async(id:string)=>(await http.get<PublishPreview>(eventPath(id)+'/publish-preview')).data,
 publish:async(id:string)=>(await http.post<PublishResult>(eventPath(id)+'/publish',undefined,{timeout:30000})).data,
}
export const issueMessages:Record<string,string>={NO_SESSIONS:'请至少添加一个场次',VENUE_EMPTY:'场馆没有有效座位',EVENT_WINDOW_ENDED:'售票结束时间已过',SESSION_START_NOT_FUTURE:'场次开始时间必须在未来',SESSION_GATE_INVALID:'入场时间必须早于开始时间',SESSION_WINDOW_EMPTY:'场次与售票窗口没有重叠',ZONE_PRICE_MISSING:'区域尚未设置票价',ZONE_PRICE_INVALID:'区域票价必须大于零',SESSION_VENUE_MISMATCH:'场次与活动场馆不一致'}
