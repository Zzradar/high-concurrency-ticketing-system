import type { Seat, SeatAvailability, SeatStatic, SeatStatus } from '../types'

export interface SeatStatusCounts {
  total: number
  available: number
  held: number
  sold: number
}

export interface SeatZoneSummary extends SeatStatusCounts {
  zone: string
}

export function mergeSeatSnapshot(
  layout: SeatStatic[],
  availability: SeatAvailability[],
): Seat[] {
  const layoutIds = new Set<string>()
  layout.forEach((seat) => {
    if (layoutIds.has(seat.id)) throw new Error('Duplicate layout seat ' + seat.id)
    layoutIds.add(seat.id)
  })

  const statusById = new Map<string, SeatStatus>()
  availability.forEach((seat) => {
    if (statusById.has(seat.id)) throw new Error('Duplicate availability seat ' + seat.id)
    if (!layoutIds.has(seat.id)) throw new Error('Unknown availability seat ' + seat.id)
    statusById.set(seat.id, seat.status)
  })

  return layout.map((seat) => {
    const status = statusById.get(seat.id)
    if (!status) throw new Error('Missing availability for seat ' + seat.id)
    return { ...seat, status }
  })
}

export function normalizeLegacySeatSnapshot(seats: Seat[]): Seat[] {
  const layout: SeatStatic[] = seats.map(({ status: _status, ...seat }) => seat)
  const availability: SeatAvailability[] = seats.map(({ id, status }) => ({ id, status }))
  return mergeSeatSnapshot(layout, availability)
}

export function countSeatStatuses(seats: Seat[]): SeatStatusCounts {
  const counts: Record<SeatStatus, number> = {
    AVAILABLE: 0,
    HELD: 0,
    SOLD: 0,
  }
  seats.forEach((seat) => {
    counts[seat.status] += 1
  })
  return {
    total: seats.length,
    available: counts.AVAILABLE,
    held: counts.HELD,
    sold: counts.SOLD,
  }
}

export function summarizeSeatZones(seats: Seat[]): SeatZoneSummary[] {
  const zones = new Map<string, Seat[]>()
  seats.forEach((seat) => {
    const zoneSeats = zones.get(seat.zone) ?? []
    zoneSeats.push(seat)
    zones.set(seat.zone, zoneSeats)
  })
  return [...zones.entries()].map(([zone, zoneSeats]) => ({
    zone,
    ...countSeatStatuses(zoneSeats),
  }))
}
