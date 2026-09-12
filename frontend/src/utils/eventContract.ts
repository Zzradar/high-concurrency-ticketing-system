import type { SalesWindow, TicketEvent } from '../types'

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
function instant(value: unknown): value is string {
  if (typeof value !== 'string') return false
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value)
  if (!parts || !Number.isFinite(Date.parse(value))) return false
  const year = Number(parts[1]), month = Number(parts[2]), day = Number(parts[3])
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]! &&
    Number(parts[4]) < 24 && Number(parts[5]) < 60 && Number(parts[6]) < 60 &&
    (!parts[7] || (Number(parts[8]) <= 23 && Number(parts[9]) < 60))
}

export function isSalesWindow(value: unknown): value is SalesWindow {
  return record(value) && instant(value.startsAt) && instant(value.endsAt) &&
    instant(value.evaluatedAt) && Date.parse(value.startsAt) < Date.parse(value.endsAt) &&
    typeof value.state === 'string' && ['NOT_STARTED', 'OPEN', 'ENDED'].includes(value.state)
}

export function isTicketEvent(value: unknown): value is TicketEvent {
  return record(value) && ['id', 'name', 'description', 'city', 'venue', 'dateRange', 'cover', 'category']
    .every(key => typeof value[key] === 'string') && value.id !== '' && value.name !== '' &&
    typeof value.status === 'string' && ['ON_SALE', 'COMING_SOON'].includes(value.status) &&
    Number.isSafeInteger(value.sessionCount) && Number(value.sessionCount) >= 0 && isSalesWindow(value.salesWindow)
}
