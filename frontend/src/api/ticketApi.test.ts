import { beforeEach, describe, expect, it } from 'vitest'
import {
  apiRequestHeaders,
  buildCheckoutSeatReplacementRequest,
  checkoutSessionPaths,
  buildReservationRequest,
  normalizeApiError,
  resetMockData,
  setMockLatency,
  TicketApiError,
  ticketApi,
} from './ticketApi'

describe('ticketApi contract and mock transaction flow', () => {
  beforeEach(() => {
    resetMockData()
    setMockLatency(0)
  })

  it('uses camelCase reservation fields and the demo user header', () => {
    expect(buildReservationRequest('session-1', ['seat-1'])).toEqual({
      sessionId: 'session-1',
      seatIds: ['seat-1'],
    })
    expect(apiRequestHeaders['X-User-Id']).toBe('U-1001')
    expect(buildCheckoutSeatReplacementRequest(['seat-1'], 3)).toEqual({
      seatIds: ['seat-1'],
      expectedRevision: 3,
    })
  })

  it('uses the frozen checkout session API paths', () => {
    expect(checkoutSessionPaths.collection).toBe('/checkout-sessions')
    expect(checkoutSessionPaths.item('C1')).toBe('/checkout-sessions/C1')
    expect(checkoutSessionPaths.seats('C1')).toBe('/checkout-sessions/C1/seats')
    expect(checkoutSessionPaths.confirm('C1')).toBe('/checkout-sessions/C1/confirm')
    expect(checkoutSessionPaths.abandon('C1')).toBe('/checkout-sessions/C1/abandon')
  })

  it('creates, reads, lists and revises a recoverable checkout session', async () => {
    const checkout = await ticketApi.createCheckoutSession('ses-concert-1001', [
      'ses-concert-1001-A01',
    ])
    expect(checkout).toMatchObject({ status: 'SELECTING', revision: 0 })

    expect(await ticketApi.getCheckoutSession(checkout.id)).toEqual(checkout)
    expect(await ticketApi.listRecoverableCheckoutSessions('ses-concert-1001')).toEqual([
      checkout,
    ])

    const revised = await ticketApi.replaceCheckoutSessionSeats(
      checkout.id,
      ['ses-concert-1001-A01', 'ses-concert-1001-A02'],
      0,
    )
    expect(revised).toMatchObject({
      revision: 1,
      seatIds: ['ses-concert-1001-A01', 'ses-concert-1001-A02'],
    })
    await expect(
      ticketApi.replaceCheckoutSessionSeats(
        checkout.id,
        ['ses-concert-1001-A04'],
        0,
      ),
    ).rejects.toMatchObject({ code: 'CHECKOUT_SESSION_VERSION_CONFLICT' })
    expect(await ticketApi.getCheckoutSession(checkout.id)).toEqual(revised)
  })

  it('confirms once, returns the same order on retry, and guards abandon', async () => {
    const checkout = await ticketApi.createCheckoutSession('ses-concert-1002', [
      'ses-concert-1002-A01',
    ])
    const [first, second] = await Promise.all([
      ticketApi.confirmCheckoutSession(checkout.id),
      ticketApi.confirmCheckoutSession(checkout.id),
    ])
    expect(first.status).toBe('RESERVED')
    expect(second.order?.id).toBe(first.order?.id)
    expect((await ticketApi.confirmCheckoutSession(checkout.id)).order?.id).toBe(
      first.order?.id,
    )
    await expect(ticketApi.abandonCheckoutSession(checkout.id)).rejects.toMatchObject({
      code: 'CHECKOUT_SESSION_NOT_ABANDONABLE',
    })
  })

  it('abandons only selecting checkout sessions and removes them from recovery', async () => {
    const checkout = await ticketApi.createCheckoutSession('ses-concert-1003', [
      'ses-concert-1003-A01',
    ])
    const abandoned = await ticketApi.abandonCheckoutSession(checkout.id)
    expect(abandoned.status).toBe('ABANDONED')
    expect(await ticketApi.listRecoverableCheckoutSessions('ses-concert-1003')).toEqual([])
  })

  it('normalizes an Axios business error to TicketApiError', () => {
    const normalized = normalizeApiError({
      isAxiosError: true,
      response: {
        data: {
          code: 'SEAT_CONFLICT',
          message: 'Selected seats are no longer available',
        },
      },
    })

    expect(normalized).toBeInstanceOf(TicketApiError)
    expect(normalized).toMatchObject({
      code: 'SEAT_CONFLICT',
      message: 'Selected seats are no longer available',
    })
  })

  it('uses integer fen for session and seat prices', async () => {
    const sessions = await ticketApi.getSessions('evt-basketball-finals')
    const seats = await ticketApi.getSeats(sessions[0]!.id)

    expect(sessions[0]!.priceFrom).toBe(38000)
    expect(Math.min(...seats.map((seat) => seat.price))).toBe(sessions[0]!.priceFrom)
    expect(seats.every((seat) => Number.isInteger(seat.price))).toBe(true)
  })

  it('locks all selected seats and rejects a competing reservation', async () => {
    const seats = await ticketApi.getSeats('ses-concert-1001')
    const selected = seats.filter((seat) => seat.status === 'AVAILABLE').slice(0, 2)

    const result = await ticketApi.createReservation(
      'ses-concert-1001',
      selected.map((seat) => seat.id),
    )
    expect(result.order.status).toBe('PENDING_PAYMENT')
    expect(result.order.totalAmount).toBe(selected.reduce((sum, seat) => sum + seat.price, 0))

    await expect(
      ticketApi.createReservation('ses-concert-1001', [selected[0]!.id]),
    ).rejects.toMatchObject({ code: 'SEAT_CONFLICT' })

    const latestSeats = await ticketApi.getSeats('ses-concert-1001')
    expect(
      latestSeats
        .filter((seat) => result.order.seatIds.includes(seat.id))
        .every((seat) => seat.status === 'HELD'),
    ).toBe(true)
  })

  it('cancels an order and releases every held seat', async () => {
    const seats = await ticketApi.getSeats('ses-concert-1002')
    const selected = seats.filter((seat) => seat.status === 'AVAILABLE').slice(0, 3)
    const { order } = await ticketApi.createReservation(
      'ses-concert-1002',
      selected.map((seat) => seat.id),
    )

    const cancelled = await ticketApi.cancelOrder(order.id)
    expect(cancelled.status).toBe('CANCELLED')

    const latestSeats = await ticketApi.getSeats('ses-concert-1002')
    expect(
      latestSeats
        .filter((seat) => order.seatIds.includes(seat.id))
        .every((seat) => seat.status === 'AVAILABLE'),
    ).toBe(true)
  })

  it('marks every reserved seat sold after payment', async () => {
    const seats = await ticketApi.getSeats('ses-basketball-2001')
    const selected = seats.filter((seat) => seat.status === 'AVAILABLE').slice(0, 2)
    const { order } = await ticketApi.createReservation(
      'ses-basketball-2001',
      selected.map((seat) => seat.id),
    )

    const paid = await ticketApi.payOrder(order.id)
    expect(paid.status).toBe('PAID')

    const latestSeats = await ticketApi.getSeats('ses-basketball-2001')
    expect(
      latestSeats
        .filter((seat) => order.seatIds.includes(seat.id))
        .every((seat) => seat.status === 'SOLD'),
    ).toBe(true)
  })

  it('expires an order in demo mode and releases every held seat', async () => {
    const seats = await ticketApi.getSeats('ses-concert-1003')
    const selected = seats.filter((seat) => seat.status === 'AVAILABLE').slice(0, 2)
    const { order } = await ticketApi.createReservation(
      'ses-concert-1003',
      selected.map((seat) => seat.id),
    )

    const expired = await ticketApi.expireOrderForDemo(order.id)
    expect(expired.status).toBe('EXPIRED')

    const latestSeats = await ticketApi.getSeats('ses-concert-1003')
    expect(
      latestSeats
        .filter((seat) => order.seatIds.includes(seat.id))
        .every((seat) => seat.status === 'AVAILABLE'),
    ).toBe(true)
  })
})
