import type { SeatAvailabilitySyncResponse } from '../types'
import { validPollHint } from './pollingPolicy'
export function isAvailabilitySync(value: unknown): value is SeatAvailabilitySyncResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const v=value as Record<string,unknown>
  if (typeof v.sessionId !== 'string' || typeof v.zone !== 'string' || !['snapshot','delta'].includes(v.mode as string)) return false
  if (typeof v.reset !== 'boolean' || typeof v.degraded !== 'boolean' || typeof v.hasMore !== 'boolean' || !validPollHint(v.pollAfterMs,v.hasMore)) return false
  if (!(v.generation === null || typeof v.generation === 'string' && v.generation.length>0) || !(v.cursor === null || typeof v.cursor === 'string' && /^(0|[1-9]\d*)-(0|[1-9]\d*)$/.test(v.cursor))) return false
  if (v.degraded && (v.mode !== 'snapshot' || v.generation !== null || v.cursor !== null || v.hasMore)) return false
  if (!v.degraded && (v.generation === null || v.cursor === null)) return false
  const seats=v.mode==='snapshot'?v.seats:v.changes
  if (!Array.isArray(seats) || !seats.every(s=>s && typeof s.id==='string' && ['AVAILABLE','HELD','SOLD'].includes(s.status))) return false
  return Array.isArray(v.zones) && v.zones.every(z=>z && typeof z.zone==='string' && ['total','available','held','sold'].every(key=>typeof z[key]==='number' && Number.isSafeInteger(z[key]) && z[key]>=0) && z.total===z.available+z.held+z.sold)
}
