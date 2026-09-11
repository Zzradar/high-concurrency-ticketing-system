import type { Seat, SeatAvailabilitySyncResponse, SeatStatic, SeatStatus, SeatZoneAvailabilitySummary } from '../types'

export class ZoneAvailabilityState {
  readonly statusBySeatId = new Map<string, SeatStatus>()
  readonly sync = new Map<string, { loaded: boolean; generation: string | null; cursor: string | null; degraded: boolean }>()
  summaries: SeatZoneAvailabilitySummary[] = []
  readonly layout: SeatStatic[]
  constructor(layout: SeatStatic[]) { this.layout = layout }

  apply(response: SeatAvailabilitySyncResponse) {
    const members = this.layout.filter(s => s.zone === response.zone)
    const ids = new Set(members.map(s => s.id))
    const changes = response.mode === 'snapshot' ? response.seats : response.changes
    if (!Array.isArray(changes)) throw new Error('Invalid availability response')
    const seen = new Set<string>()
    for (const seat of changes) {
      if (!ids.has(seat.id) || seen.has(seat.id) || !['AVAILABLE','HELD','SOLD'].includes(seat.status)) throw new Error('Invalid zone seat')
      seen.add(seat.id)
    }
    if (response.mode === 'snapshot' && seen.size !== ids.size) throw new Error('Incomplete zone snapshot')
    const previous = this.sync.get(response.zone)
    if (response.mode === 'delta' && (!previous?.loaded || previous.generation !== response.generation)) throw new Error('Unexpected delta generation')
    if (response.mode === 'snapshot') for (const id of ids) this.statusBySeatId.delete(id)
    for (const seat of changes) this.statusBySeatId.set(seat.id,seat.status)
    this.sync.set(response.zone,{loaded:true,generation:response.generation,cursor:response.cursor,degraded:response.degraded})
    this.summaries = response.zones
  }

  seats(): Seat[] {
    return this.layout.flatMap(seat => {
      const status = this.statusBySeatId.get(seat.id)
      return status ? [{...seat,status}] : []
    })
  }
}
