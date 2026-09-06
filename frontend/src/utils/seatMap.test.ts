import { describe, expect, it } from 'vitest'
import type { Seat, SeatAvailability, SeatStatic } from '../types'
import {
  countSeatStatuses,
  mergeSeatSnapshot,
  normalizeLegacySeatSnapshot,
  summarizeSeatZones,
} from './seatMap'

const legacySeats: Seat[] = [
  { id: 'A1', sessionId: 'S1', label: 'A01', row: 'A', number: 1, zone: '星光区', price: 128000, status: 'AVAILABLE' },
  { id: 'A2', sessionId: 'S1', label: 'A02', row: 'A', number: 2, zone: '星光区', price: 128000, status: 'HELD' },
  { id: 'B1', sessionId: 'S1', label: 'B01', row: 'B', number: 1, zone: '看台 A 区', price: 88000, status: 'SOLD' },
]

describe('seat map data preparation', () => {
  it('merges static layout and dynamic availability by seat id', () => {
    const layout: SeatStatic[] = legacySeats.map(({ status: _status, ...seat }) => seat)
    const availability: SeatAvailability[] = legacySeats
      .map(({ id, status }) => ({ id, status }))
      .reverse()

    expect(mergeSeatSnapshot(layout, availability)).toEqual(legacySeats)
  })

  it('keeps the legacy getSeats snapshot contract compatible', () => {
    expect(normalizeLegacySeatSnapshot(legacySeats)).toEqual(legacySeats)
  })

  it('derives session and zone status counts from the current snapshot', () => {
    expect(countSeatStatuses(legacySeats)).toEqual({ total: 3, available: 1, held: 1, sold: 1 })
    expect(summarizeSeatZones(legacySeats)).toEqual([
      { zone: '星光区', total: 2, available: 1, held: 1, sold: 0 },
      { zone: '看台 A 区', total: 1, available: 0, held: 0, sold: 1 },
    ])
  })

  it('rejects an incomplete availability snapshot instead of inventing a status', () => {
    const layout: SeatStatic[] = legacySeats.map(({ status: _status, ...seat }) => seat)
    expect(() => mergeSeatSnapshot(layout, [])).toThrow('Missing availability for seat A1')
  })

  it('rejects duplicate layout and availability seat ids', () => {
    const layout: SeatStatic[] = legacySeats.map(({ status: _status, ...seat }) => seat)
    const availability: SeatAvailability[] = legacySeats.map(({ id, status }) => ({ id, status }))

    expect(() => mergeSeatSnapshot([...layout, layout[0]!], availability)).toThrow(
      'Duplicate layout seat A1',
    )
    expect(() => mergeSeatSnapshot(layout, [...availability, availability[0]!])).toThrow(
      'Duplicate availability seat A1',
    )
  })

  it('rejects availability for a seat outside the layout', () => {
    const layout: SeatStatic[] = legacySeats.map(({ status: _status, ...seat }) => seat)
    const availability: SeatAvailability[] = [
      ...legacySeats.map(({ id, status }) => ({ id, status })),
      { id: 'UNKNOWN', status: 'AVAILABLE' },
    ]

    expect(() => mergeSeatSnapshot(layout, availability)).toThrow(
      'Unknown availability seat UNKNOWN',
    )
  })
})
