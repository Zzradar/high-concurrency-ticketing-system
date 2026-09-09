export type ViewName = 'event-list' | 'session-list' | 'seat-selection' | 'order'

export type EventStatus = 'ON_SALE' | 'COMING_SOON'
export type SessionStatus = 'ON_SALE' | 'SOLD_OUT'
export type SeatStatus = 'AVAILABLE' | 'HELD' | 'SOLD'
export type ReservationStatus = 'ACTIVE' | 'CONFIRMED' | 'CANCELLED' | 'EXPIRED'
export type OrderStatus = 'PENDING_PAYMENT' | 'PAID' | 'CANCELLED' | 'EXPIRED'
export type CheckoutSessionStatus = 'SELECTING' | 'SUBMITTING' | 'RESERVED' | 'ABANDONED'
export type PaymentAttemptStatus = 'PROCESSING' | 'SUCCEEDED' | 'FAILED' | 'TIMED_OUT'
export type NotificationType =
  | 'ORDER_CREATED'
  | 'PAYMENT_SUCCEEDED'
  | 'ORDER_CANCELLED'
  | 'ORDER_EXPIRED'
  | 'AUTO_REFUND_COMPLETED'
  | 'AUTO_REFUND_FAILED'
  | 'REFUND_COMPLETED'
  | 'REFUND_FAILED'

export type RefundStatus = 'PROCESSING' | 'SUCCEEDED' | 'FAILED'
export type RefundSource = 'BUYER' | 'SYSTEM'
export type RefundReason = 'BUYER_REQUESTED'
  | 'ORDER_CANCELLED_BEFORE_PAYMENT_CONFIRMATION'
  | 'ORDER_EXPIRED_BEFORE_PAYMENT_CONFIRMATION'
  | 'DUPLICATE_LATE_PAYMENT' | 'PAYMENT_NOT_ACCEPTED'

export interface BuyerRefundSummary {
  id: string
  orderId: string
  source: 'BUYER'
  reason: 'BUYER_REQUESTED'
  status: RefundStatus
  amount: number // 整数最小货币单位
  currency: string
}

export interface Refund extends Omit<BuyerRefundSummary, 'source' | 'reason'> {
  source: RefundSource
  reason: RefundReason
  paymentAttemptId: string
  createdAt: string
  refundedAt?: string
  failedAt?: string
  failureCode?: 'PROVIDER_REFUND_FAILED'
}

export interface RefundEligibility {
  eligible: boolean
  deadline: string
  reason: 'ALREADY_REQUESTED' | 'ORDER_NOT_REFUNDABLE' | 'REFUND_WINDOW_CLOSED' | null
}

export type CreateRefundDisposition = 'CREATED' | 'REUSED_PROCESSING' | 'REUSED_TERMINAL'
export interface CreateRefundResult {
  disposition: CreateRefundDisposition
  refund: Refund
  pollAfterMs: number
}

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
  priceFrom: number // 整数“分”
  availability: '充足' | '紧张' | '售罄'
}

export interface SeatStatic {
  id: string
  sessionId: string
  label: string
  row: string
  number: number
  zone: string
  price: number // 整数“分”
}

export type SeatLayoutItem = Omit<SeatStatic, 'sessionId'>

export interface SeatLayoutResponse {
  sessionId: string
  seats: SeatLayoutItem[]
}

export interface SeatAvailability {
  id: string
  status: SeatStatus
}

export interface SeatAvailabilityResponse {
  sessionId: string
  seats: SeatAvailability[]
}

export interface Seat extends SeatStatic {
  status: SeatStatus
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
  totalAmount: number // 整数“分”
  expiresAt: string
  createdAt: string
  paidAt?: string
  buyerRefund: BuyerRefundSummary | null
  refundEligibility?: RefundEligibility // 订单列表和部分写操作响应省略；详情始终返回
}

export interface ReservationResult {
  reservation: Reservation
  order: TicketOrder
}

export interface CheckoutSession {
  id: string
  userId: string
  sessionId: string
  seatIds: string[]
  status: CheckoutSessionStatus
  revision: number
  reservationId?: string
  createdAt: string
  updatedAt: string
  reservation?: Reservation
  order?: TicketOrder
}

export interface PaymentAttempt {
  id: string
  orderId: string
  status: PaymentAttemptStatus
  startedAt: string
  processingDeadline: string
  scheduledCompleteAt?: string
  provider: string
  providerStatus?: string
  completedAt?: string
  timedOutAt?: string
  acceptedAt?: string
  failureReason?: string
}

export interface PaymentAction {
  provider: string
  type: string
  clientSecret: string
}

export interface PaymentStartResult {
  disposition: 'STARTED_NEW' | 'REUSED_PROCESSING' | 'ALREADY_PAID'
  order: TicketOrder
  paymentAttempt: PaymentAttempt | null
  paymentAction: PaymentAction | null
}

export interface CheckoutConfirmationResult {
  disposition: 'CONFIRMED_NOW' | 'REUSED_CONFIRMATION' | 'ALREADY_CONFIRMED'
  checkoutSession: CheckoutSession
}

export interface CancelOrderResult {
  disposition: 'CANCELLED_NOW' | 'ALREADY_CANCELLED'
  order: TicketOrder
}

export interface CurrentUser {
  id: string
  username: string
  displayName: string
}

export interface UserNotification {
  id: string
  orderId: string
  type: NotificationType
  title: string
  message: string
  createdAt: string
  readAt?: string
}
