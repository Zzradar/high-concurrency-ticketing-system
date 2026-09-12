import { instant } from './timeContract'
import { isAdmissionSummary } from './admissionContract'
import type { SalesWindow, TicketEvent, TicketSession } from '../types'

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export function isSalesWindow(value: unknown): value is SalesWindow {
  return record(value) && instant(value.startsAt) && instant(value.endsAt) &&
    instant(value.evaluatedAt) && Date.parse(value.startsAt) < Date.parse(value.endsAt) &&
    typeof value.state === 'string' && ['NOT_STARTED', 'OPEN', 'ENDED'].includes(value.state)
}

export function isTicketEvent(value: unknown): value is TicketEvent {
  return record(value) && (!('admission' in value) || isAdmissionSummary(value.admission)) && ['id', 'name', 'description', 'city', 'venue', 'dateRange', 'cover', 'category']
    .every(key => typeof value[key] === 'string') && value.id !== '' && value.name !== '' &&
    typeof value.status === 'string' && ['ON_SALE', 'COMING_SOON'].includes(value.status) &&
    Number.isSafeInteger(value.sessionCount) && Number(value.sessionCount) >= 0 && isSalesWindow(value.salesWindow)
}

export function isTicketSession(value:unknown):value is TicketSession {
 return record(value) && ['id','eventId','date','time','weekday','venue','gateTime'].every(key=>typeof value[key]==='string' && value[key]!=='') &&
  typeof value.status==='string' && ['ON_SALE','SOLD_OUT'].includes(value.status) && typeof value.priceFrom==='number' && Number.isSafeInteger(value.priceFrom) && value.priceFrom>=0 &&
  typeof value.availability==='string' && ['充足','紧张','售罄'].includes(value.availability) && isSalesWindow(value.salesWindow) &&
  (!('admission' in value) || isAdmissionSummary(value.admission))
}
