export type ViewName = 'event-list' | 'session-list' | 'seat-selection' | 'order'

export type EventStatus = 'ON_SALE' | 'COMING_SOON'
export type SessionStatus = 'ON_SALE' | 'SOLD_OUT'
export type SeatStatus = 'AVAILABLE' | 'HELD' | 'SOLD'
export type ReservationStatus = 'ACTIVE' | 'CONFIRMED' | 'CANCELLED' | 'EXPIRED'
export type OrderStatus = 'PENDING_PAYMENT' | 'PAID' | 'CANCELLED' | 'EXPIRED'

export interface TicketEvent {
  id: string
  name: string
  description: string
  city: string
  venue: string
  dateRange: string
  status: EventStatus
  cover: string
  sessionCount: number
  category: string
}

export interface TicketSession {
  id: string
  eventId: string
  date: string
  time: string
  weekday: string
  venue: string
  gateTime: string
  status: SessionStatus
  priceFrom: number
  availability: '充足' | '紧张' | '售罄'
}

export interface Seat {
  id: string
  sessionId: string
  label: string
  row: string
  number: number
  status: SeatStatus
  zone: string
  price: number
}

export interface Reservation {
  id: string
  userId: string
  sessionId: string
  seatIds: string[]
  status: ReservationStatus
  expiresAt: string
  createdAt: string
}

export interface TicketOrder {
  id: string
  reservationId: string
  eventId: string
  sessionId: string
  seatIds: string[]
  status: OrderStatus
  totalAmount: number
  expiresAt: string
  createdAt: string
  paidAt?: string
}

export interface ReservationResult {
  reservation: Reservation
  order: TicketOrder
}
