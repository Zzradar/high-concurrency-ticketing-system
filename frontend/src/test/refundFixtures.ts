import type { BuyerRefundSummary, Refund, TicketOrder } from '../types'

// Exact public JSON shapes from TicketDtos.h and OrderRepository.cpp (Phase 12-1).
export const refundFixture: Refund = {
  id: 'RFD-test', orderId: 'O1', paymentAttemptId: 'PAY-test', source: 'BUYER',
  reason: 'BUYER_REQUESTED', status: 'PROCESSING', amount: 12800, currency: 'cny',
  createdAt: '2026-09-09T02:00:00.000Z',
}
export const summaryFixture: BuyerRefundSummary = {
  id: 'RFD-test', orderId: 'O1', source: 'BUYER', reason: 'BUYER_REQUESTED',
  status: 'PROCESSING', amount: 12800, currency: 'cny',
}
export const orderFixture: TicketOrder = {
  id: 'O1', reservationId: 'R1', eventId: 'E1', sessionId: 'S1', seatIds: [],
  status: 'PAID', totalAmount: 12800, createdAt: '2026-09-09T01:00:00.000Z',
  expiresAt: '2026-09-09T01:15:00.000Z', paidAt: '2026-09-09T01:01:00.000Z',
  buyerRefund: null,
  refundEligibility: { eligible: true, deadline: '2026-10-01T11:30:00.000Z', reason: null },
}
