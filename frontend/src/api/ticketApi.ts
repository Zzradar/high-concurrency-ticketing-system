import axios from 'axios'
import type {
  CheckoutSession,
  PaymentAttempt,
  PaymentStartResult,
  Reservation,
  ReservationResult,
  Seat,
  TicketEvent,
  TicketOrder,
  TicketSession,
  UserNotification,
} from '../types'

export class TicketApiError extends Error {
  readonly code: string

  constructor(message: string, code: string) {
    super(message)
    this.name = 'TicketApiError'
    this.code = code
  }
}

interface ApiErrorPayload {
  code?: unknown
  message?: unknown
}

export const DEMO_USER_ID = 'U-1001'
export const apiRequestHeaders = {
  'Content-Type': 'application/json',
  'X-User-Id': DEMO_USER_ID,
} as const

export const checkoutSessionPaths = {
  collection: '/checkout-sessions',
  item: (id: string) => '/checkout-sessions/' + id,
  seats: (id: string) => '/checkout-sessions/' + id + '/seats',
  confirm: (id: string) => '/checkout-sessions/' + id + '/confirm',
  abandon: (id: string) => '/checkout-sessions/' + id + '/abandon',
} as const

export function normalizeApiError(error: unknown): unknown {
  if (!axios.isAxiosError<ApiErrorPayload>(error)) return error

  const code = error.response?.data?.code
  const message = error.response?.data?.message
  if (typeof code === 'string' && typeof message === 'string') {
    return new TicketApiError(message, code)
  }

  return error
}

const http = axios.create({
  baseURL: '/api',
  timeout: 8000,
  headers: apiRequestHeaders,
})

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(normalizeApiError(error)),
)

export const isMockMode =
  import.meta.env.MODE === 'test' || import.meta.env.VITE_USE_MOCK_API !== 'false'

const eventsSeed: TicketEvent[] = [
  {
    id: 'evt-concert-2026',
    name: '星海回响 · 2026 巡演',
    description: '沉浸式环形舞台与全景声现场，和三万名观众一起点亮这个夜晚。',
    city: '上海',
    venue: '上海体育场',
    dateRange: '2026.10.01 — 10.03',
    status: 'ON_SALE',
    cover: '/images/concert-cover.png',
    sessionCount: 3,
    category: '演唱会',
  },
  {
    id: 'evt-basketball-finals',
    name: '城市巅峰 · 篮球总决赛',
    description: '年度冠军之夜，见证最后一球落下前的每一次攻防与呐喊。',
    city: '上海',
    venue: '浦东体育中心',
    dateRange: '2026.11.08 — 11.09',
    status: 'ON_SALE',
    cover: '/images/basketball-cover.png',
    sessionCount: 2,
    category: '体育赛事',
  },
]

const sessionsSeed: Record<string, TicketSession[]> = {
  'evt-concert-2026': [
    {
      id: 'ses-concert-1001',
      eventId: 'evt-concert-2026',
      date: '10月01日',
      time: '19:30',
      weekday: '周四',
      venue: '上海体育场 · 主场馆',
      gateTime: '17:30',
      status: 'ON_SALE',
      priceFrom: 58000,
      availability: '紧张',
    },
    {
      id: 'ses-concert-1002',
      eventId: 'evt-concert-2026',
      date: '10月02日',
      time: '19:30',
      weekday: '周五',
      venue: '上海体育场 · 主场馆',
      gateTime: '17:30',
      status: 'ON_SALE',
      priceFrom: 58000,
      availability: '充足',
    },
    {
      id: 'ses-concert-1003',
      eventId: 'evt-concert-2026',
      date: '10月03日',
      time: '19:30',
      weekday: '周六',
      venue: '上海体育场 · 主场馆',
      gateTime: '17:30',
      status: 'ON_SALE',
      priceFrom: 58000,
      availability: '充足',
    },
  ],
  'evt-basketball-finals': [
    {
      id: 'ses-basketball-2001',
      eventId: 'evt-basketball-finals',
      date: '11月08日',
      time: '18:30',
      weekday: '周日',
      venue: '浦东体育中心 · 一号馆',
      gateTime: '17:00',
      status: 'ON_SALE',
      priceFrom: 38000,
      availability: '紧张',
    },
    {
      id: 'ses-basketball-2002',
      eventId: 'evt-basketball-finals',
      date: '11月09日',
      time: '19:00',
      weekday: '周一',
      venue: '浦东体育中心 · 一号馆',
      gateTime: '17:30',
      status: 'ON_SALE',
      priceFrom: 38000,
      availability: '充足',
    },
  ],
}

let mockLatency = 180
let seatsBySession = new Map<string, Seat[]>()
let reservations = new Map<string, Reservation>()
let orders = new Map<string, TicketOrder>()
let checkoutSessions = new Map<string, CheckoutSession>()
let checkoutConfirmations = new Map<string, Promise<CheckoutSession>>()
let paymentAttempts = new Map<string, PaymentAttempt>()
let notifications: UserNotification[] = []
let sequence = 24082600
let mockPaymentDelayMilliseconds: number | null = null
let mockPaymentOutcome: 'SUCCESS' | 'FAILURE' | null = null

const clone = <T>(value: T): T => structuredClone(value)
const wait = () => new Promise((resolve) => setTimeout(resolve, mockLatency))

function createSeats(sessionId: string): Seat[] {
  const unavailableHeld = new Set(['A03', 'B07', 'D04', 'F09'])
  const unavailableSold = new Set(['A08', 'C05', 'C06', 'E02', 'E03'])
  const rows = ['A', 'B', 'C', 'D', 'E', 'F']
  const isBasketball = sessionId.startsWith('ses-basketball-')

  return rows.flatMap((row, rowIndex) =>
    Array.from({ length: 10 }, (_, index) => {
      const number = index + 1
      const label = row + String(number).padStart(2, '0')
      const zone = rowIndex < 2 ? '星光区' : rowIndex < 4 ? '看台 A 区' : '看台 B 区'
      const price = isBasketball
        ? rowIndex < 2
          ? 88000
          : rowIndex < 4
            ? 58000
            : 38000
        : rowIndex < 2
          ? 128000
          : rowIndex < 4
            ? 88000
            : 58000
      return {
        id: sessionId + '-' + label,
        sessionId,
        label,
        row,
        number,
        status: unavailableHeld.has(label)
          ? 'HELD'
          : unavailableSold.has(label)
            ? 'SOLD'
            : 'AVAILABLE',
        zone,
        price,
      }
    }),
  )
}

function ensureSeats(sessionId: string) {
  if (!seatsBySession.has(sessionId)) {
    seatsBySession.set(sessionId, createSeats(sessionId))
  }
  return seatsBySession.get(sessionId)!
}

function releaseReservation(order: TicketOrder, status: 'CANCELLED' | 'EXPIRED') {
  order.status = status
  const reservation = reservations.get(order.reservationId)
  if (reservation) reservation.status = status

  const seats = ensureSeats(order.sessionId)
  seats.forEach((seat) => {
    if (order.seatIds.includes(seat.id) && seat.status === 'HELD') seat.status = 'AVAILABLE'
  })
}

function addNotification(
  order: TicketOrder,
  type: UserNotification['type'],
  title: string,
  message: string,
  dedupeKey: string,
) {
  if (notifications.some((item) => item.id === dedupeKey)) return
  notifications.unshift({
    id: dedupeKey,
    orderId: order.id,
    type,
    title,
    message,
    createdAt: new Date().toISOString(),
  })
}

function activeProcessingAttempt(orderId: string) {
  return [...paymentAttempts.values()].find(
    (attempt) =>
      attempt.orderId === orderId &&
      attempt.status === 'PROCESSING' &&
      Date.parse(attempt.processingDeadline) > Date.now(),
  )
}

function timeoutExpiredProcessingAttempts(orderId: string) {
  const now = Date.now()
  paymentAttempts.forEach((attempt) => {
    if (
      attempt.orderId === orderId &&
      attempt.status === 'PROCESSING' &&
      Date.parse(attempt.processingDeadline) <= now
    ) {
      attempt.status = 'TIMED_OUT'
      attempt.timedOutAt = new Date(now).toISOString()
    }
  })
}

function synchronizeExpiry(order: TicketOrder) {
  timeoutExpiredProcessingAttempts(order.id)
  if (
    order.status === 'PENDING_PAYMENT' &&
    Date.parse(order.expiresAt) <= Date.now() &&
    !activeProcessingAttempt(order.id)
  ) {
    releaseReservation(order, 'EXPIRED')
    addNotification(order, 'ORDER_EXPIRED', '订单已过期', '订单支付时间已结束，所选座位已释放。', 'order-expired:' + order.id)
  }
}

async function mockGetEvents() {
  await wait()
  return clone(eventsSeed)
}

async function mockGetSessions(eventId: string) {
  await wait()
  return clone(sessionsSeed[eventId] ?? [])
}

async function mockGetSeats(sessionId: string) {
  await wait()
  return clone(ensureSeats(sessionId))
}

async function mockCreateReservation(sessionId: string, seatIds: string[]): Promise<ReservationResult> {
  await wait()
  const seats = ensureSeats(sessionId)
  const requested = seats.filter((seat) => seatIds.includes(seat.id))

  if (requested.length !== seatIds.length || requested.some((seat) => seat.status !== 'AVAILABLE')) {
    throw new TicketApiError('所选座位已发生变化，请重新选择。', 'SEAT_CONFLICT')
  }

  requested.forEach((seat) => {
    seat.status = 'HELD'
  })

  const now = new Date()
  const expiresAt = new Date(now.getTime() + 15 * 60 * 1000).toISOString()
  const reservationId = 'RSV-' + ++sequence
  const orderId = 'TKT-' + ++sequence
  const session = Object.values(sessionsSeed)
    .flat()
    .find((item) => item.id === sessionId)

  if (!session) throw new TicketApiError('场次不存在。', 'SESSION_NOT_FOUND')

  const reservation: Reservation = {
    id: reservationId,
    userId: 'U-1001',
    sessionId,
    seatIds: [...seatIds],
    status: 'ACTIVE',
    expiresAt,
    createdAt: now.toISOString(),
  }
  const order: TicketOrder = {
    id: orderId,
    reservationId,
    eventId: session.eventId,
    sessionId,
    seatIds: [...seatIds],
    status: 'PENDING_PAYMENT',
    totalAmount: requested.reduce((total, seat) => total + seat.price, 0),
    expiresAt,
    createdAt: now.toISOString(),
  }

  reservations.set(reservation.id, reservation)
  orders.set(order.id, order)
  return clone({ reservation, order })
}

function validateCheckoutSeatIds(sessionId: string, seatIds: string[], minimum: number) {
  const unique = new Set(seatIds)
  const inventory = new Set(ensureSeats(sessionId).map((seat) => seat.id))
  if (
    seatIds.length < minimum ||
    seatIds.length > 6 ||
    unique.size !== seatIds.length ||
    seatIds.some((seatId) => typeof seatId !== 'string' || !inventory.has(seatId))
  ) {
    throw new TicketApiError('购票会话请求无效。', 'INVALID_ARGUMENT')
  }
}

async function mockCreateCheckoutSession(
  sessionId: string,
  seatIds: string[],
): Promise<CheckoutSession> {
  await wait()
  const session = Object.values(sessionsSeed)
    .flat()
    .find((item) => item.id === sessionId)
  if (!session) throw new TicketApiError('场次不存在。', 'SESSION_NOT_FOUND')
  validateCheckoutSeatIds(sessionId, seatIds, 1)
  const now = new Date().toISOString()
  const checkout: CheckoutSession = {
    id: 'CHK-' + ++sequence,
    userId: DEMO_USER_ID,
    sessionId,
    seatIds: [...seatIds].sort(),
    status: 'SELECTING',
    revision: 0,
    createdAt: now,
    updatedAt: now,
  }
  checkoutSessions.set(checkout.id, checkout)
  return clone(checkout)
}

async function mockGetCheckoutSession(id: string): Promise<CheckoutSession> {
  await wait()
  const checkout = checkoutSessions.get(id)
  if (!checkout || checkout.userId !== DEMO_USER_ID) {
    throw new TicketApiError('未找到该购票会话。', 'CHECKOUT_SESSION_NOT_FOUND')
  }
  return clone(checkout)
}

async function mockListRecoverableCheckoutSessions(
  sessionId: string,
): Promise<CheckoutSession[]> {
  await wait()
  return clone(
    [...checkoutSessions.values()]
      .filter(
        (checkout) =>
          checkout.userId === DEMO_USER_ID &&
          checkout.sessionId === sessionId &&
          (checkout.status === 'SELECTING' || checkout.status === 'SUBMITTING'),
      )
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
  )
}

async function mockReplaceCheckoutSessionSeats(
  id: string,
  seatIds: string[],
  expectedRevision: number,
): Promise<CheckoutSession> {
  await wait()
  const checkout = checkoutSessions.get(id)
  if (!checkout) {
    throw new TicketApiError('未找到该购票会话。', 'CHECKOUT_SESSION_NOT_FOUND')
  }
  if (checkout.status !== 'SELECTING') {
    throw new TicketApiError('当前购票会话不能修改座位。', 'CHECKOUT_SESSION_NOT_MODIFIABLE')
  }
  if (checkout.revision !== expectedRevision) {
    throw new TicketApiError(
      '该购票会话已在其他页面发生修改。',
      'CHECKOUT_SESSION_VERSION_CONFLICT',
    )
  }
  validateCheckoutSeatIds(checkout.sessionId, seatIds, 0)
  checkout.seatIds = [...seatIds].sort()
  checkout.revision += 1
  checkout.updatedAt = new Date().toISOString()
  return clone(checkout)
}

function startMockCheckoutConfirmation(checkout: CheckoutSession) {
  const pending = mockCreateReservation(checkout.sessionId, checkout.seatIds)
    .then((result) => {
      checkout.status = 'RESERVED'
      checkout.reservationId = result.reservation.id
      checkout.reservation = result.reservation
      checkout.order = result.order
      checkout.updatedAt = new Date().toISOString()
      return clone(checkout)
    })
    .catch((error: unknown) => {
      if (error instanceof TicketApiError && error.code === 'SEAT_CONFLICT') {
        checkout.status = 'SELECTING'
        checkout.updatedAt = new Date().toISOString()
      }
      throw error
    })
    .finally(() => checkoutConfirmations.delete(checkout.id))
  checkoutConfirmations.set(checkout.id, pending)
  return pending
}

async function mockConfirmCheckoutSession(id: string): Promise<CheckoutSession> {
  await wait()
  const checkout = checkoutSessions.get(id)
  if (!checkout) {
    throw new TicketApiError('未找到该购票会话。', 'CHECKOUT_SESSION_NOT_FOUND')
  }
  if (checkout.status === 'RESERVED') return clone(checkout)
  if (checkout.status === 'ABANDONED' || checkout.seatIds.length === 0) {
    throw new TicketApiError('当前购票会话不能确认。', 'CHECKOUT_SESSION_NOT_CONFIRMABLE')
  }
  const existing = checkoutConfirmations.get(id)
  if (existing) return clone(await existing)
  checkout.status = 'SUBMITTING'
  checkout.updatedAt = new Date().toISOString()
  return clone(await startMockCheckoutConfirmation(checkout))
}

async function mockAbandonCheckoutSession(id: string): Promise<CheckoutSession> {
  await wait()
  const checkout = checkoutSessions.get(id)
  if (!checkout) {
    throw new TicketApiError('未找到该购票会话。', 'CHECKOUT_SESSION_NOT_FOUND')
  }
  if (checkout.status === 'ABANDONED') return clone(checkout)
  if (checkout.status !== 'SELECTING') {
    throw new TicketApiError('当前购票会话不能放弃。', 'CHECKOUT_SESSION_NOT_ABANDONABLE')
  }
  checkout.status = 'ABANDONED'
  checkout.updatedAt = new Date().toISOString()
  return clone(checkout)
}

async function mockGetOrder(orderId: string) {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  synchronizeExpiry(order)
  return clone(order)
}

function finishMockPayment(attemptId: string, outcome: 'SUCCESS' | 'FAILURE') {
  const attempt = paymentAttempts.get(attemptId)
  if (!attempt || !['PROCESSING', 'TIMED_OUT'].includes(attempt.status)) return
  const order = orders.get(attempt.orderId)
  if (!order) return
  const now = new Date()
  attempt.completedAt = now.toISOString()
  if (outcome === 'FAILURE') {
    attempt.status = 'FAILED'
    attempt.failureReason = 'SIMULATED_PAYMENT_FAILURE'
    synchronizeExpiry(order)
    return
  }

  attempt.status = 'SUCCEEDED'
  const accepted =
    order.status === 'PENDING_PAYMENT' &&
    now.getTime() < Date.parse(attempt.processingDeadline) &&
    Date.parse(attempt.startedAt) < Date.parse(order.expiresAt)
  if (accepted) {
    attempt.acceptedAt = attempt.completedAt
    order.status = 'PAID'
    order.paidAt = attempt.completedAt
    const reservation = reservations.get(order.reservationId)
    if (reservation) reservation.status = 'CONFIRMED'
    ensureSeats(order.sessionId).forEach((seat) => {
      if (order.seatIds.includes(seat.id)) seat.status = 'SOLD'
    })
    addNotification(order, 'PAYMENT_SUCCEEDED', '支付成功', '订单支付成功，座位已确认。', 'payment-succeeded:' + order.id)
    return
  }
  addNotification(
    order,
    'AUTO_REFUND_COMPLETED',
    '自动退款已完成',
    '支付结果晚于订单终态到达，款项已原路全额退回。',
    'auto-refund:' + attempt.id,
  )
  synchronizeExpiry(order)
}

async function mockPayOrder(orderId: string): Promise<PaymentStartResult> {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  synchronizeExpiry(order)
  if (order.status === 'PAID') {
    const accepted = [...paymentAttempts.values()].find(
      (attempt) => attempt.orderId === orderId && attempt.acceptedAt,
    )
    return clone({ order, paymentAttempt: accepted ?? null })
  }
  if (order.status === 'EXPIRED') {
    throw new TicketApiError('订单已过期。', 'ORDER_EXPIRED')
  }
  if (order.status !== 'PENDING_PAYMENT') {
    throw new TicketApiError('当前订单无法支付。', 'ORDER_NOT_PAYABLE')
  }
  const existing = activeProcessingAttempt(orderId)
  if (existing) return clone({ order, paymentAttempt: existing })

  const startedAt = new Date()
  const delay = mockPaymentDelayMilliseconds ?? 2000 + Math.random() * 4000
  const attempt: PaymentAttempt = {
    id: 'PAY-' + ++sequence,
    orderId,
    status: 'PROCESSING',
    startedAt: startedAt.toISOString(),
    processingDeadline: new Date(startedAt.getTime() + 10000).toISOString(),
    scheduledCompleteAt: new Date(startedAt.getTime() + delay).toISOString(),
  }
  paymentAttempts.set(attempt.id, attempt)
  const outcome = mockPaymentOutcome ?? (Math.random() < 0.01 ? 'FAILURE' : 'SUCCESS')
  window.setTimeout(() => finishMockPayment(attempt.id, outcome), delay)
  return clone({ order, paymentAttempt: attempt })
}

async function mockCancelOrder(orderId: string) {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  synchronizeExpiry(order)
  if (order.status === 'CANCELLED') return clone(order)
  if (order.status === 'EXPIRED') {
    throw new TicketApiError('订单已过期。', 'ORDER_EXPIRED')
  }
  if (order.status !== 'PENDING_PAYMENT') {
    throw new TicketApiError('当前订单无法取消。', 'ORDER_NOT_CANCELLABLE')
  }
  releaseReservation(order, 'CANCELLED')
  addNotification(order, 'ORDER_CANCELLED', '订单已取消', '订单已取消，所选座位已释放。', 'order-cancelled:' + order.id)
  return clone(order)
}

async function mockGetPaymentAttempt(attemptId: string) {
  await wait()
  const attempt = paymentAttempts.get(attemptId)
  if (!attempt) throw new TicketApiError('未找到支付尝试。', 'PAYMENT_ATTEMPT_NOT_FOUND')
  timeoutExpiredProcessingAttempts(attempt.orderId)
  return clone(attempt)
}

async function mockGetNotifications() {
  await wait()
  return clone(notifications)
}

async function mockMarkNotificationRead(notificationId: string) {
  await wait()
  const notification = notifications.find((item) => item.id === notificationId)
  if (!notification) throw new TicketApiError('未找到通知。', 'NOTIFICATION_NOT_FOUND')
  notification.readAt ??= new Date().toISOString()
  return clone(notification)
}

async function mockExpireOrder(orderId: string) {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  if (order.status === 'PENDING_PAYMENT') releaseReservation(order, 'EXPIRED')
  return clone(order)
}

export function buildReservationRequest(sessionId: string, seatIds: string[]) {
  return {
    sessionId,
    seatIds,
  }
}

export function buildCheckoutSeatReplacementRequest(
  seatIds: string[],
  expectedRevision: number,
) {
  return { seatIds, expectedRevision }
}

export function buildSeatMapRequestConfig(checkoutSessionId?: string) {
  return checkoutSessionId ? { params: { checkoutSessionId } } : undefined
}

export const ticketApi = {
  async getEvents(): Promise<TicketEvent[]> {
    if (isMockMode) return mockGetEvents()
    return (await http.get<TicketEvent[]>('/events')).data
  },
  async getSessions(eventId: string): Promise<TicketSession[]> {
    if (isMockMode) return mockGetSessions(eventId)
    return (await http.get<TicketSession[]>('/events/' + eventId + '/sessions')).data
  },
  async getSeats(sessionId: string, checkoutSessionId?: string): Promise<Seat[]> {
    if (isMockMode) return mockGetSeats(sessionId)
    return (
      await http.get<Seat[]>(
        '/sessions/' + sessionId + '/seats',
        buildSeatMapRequestConfig(checkoutSessionId),
      )
    ).data
  },
  async createReservation(sessionId: string, seatIds: string[]): Promise<ReservationResult> {
    if (isMockMode) return mockCreateReservation(sessionId, seatIds)
    return (
      await http.post<ReservationResult>(
        '/reservations',
        buildReservationRequest(sessionId, seatIds),
      )
    ).data
  },
  async createCheckoutSession(
    sessionId: string,
    seatIds: string[],
  ): Promise<CheckoutSession> {
    if (isMockMode) return mockCreateCheckoutSession(sessionId, seatIds)
    return (
      await http.post<CheckoutSession>(checkoutSessionPaths.collection, { sessionId, seatIds })
    ).data
  },
  async getCheckoutSession(id: string): Promise<CheckoutSession> {
    if (isMockMode) return mockGetCheckoutSession(id)
    return (await http.get<CheckoutSession>(checkoutSessionPaths.item(id))).data
  },
  async listRecoverableCheckoutSessions(sessionId: string): Promise<CheckoutSession[]> {
    if (isMockMode) return mockListRecoverableCheckoutSessions(sessionId)
    return (
      await http.get<CheckoutSession[]>(checkoutSessionPaths.collection, {
        params: { sessionId, recoverable: true },
      })
    ).data
  },
  async replaceCheckoutSessionSeats(
    id: string,
    seatIds: string[],
    expectedRevision: number,
  ): Promise<CheckoutSession> {
    if (isMockMode) {
      return mockReplaceCheckoutSessionSeats(id, seatIds, expectedRevision)
    }
    return (
      await http.put<CheckoutSession>(
        checkoutSessionPaths.seats(id),
        buildCheckoutSeatReplacementRequest(seatIds, expectedRevision),
      )
    ).data
  },
  async confirmCheckoutSession(id: string): Promise<CheckoutSession> {
    if (isMockMode) return mockConfirmCheckoutSession(id)
    return (await http.post<CheckoutSession>(checkoutSessionPaths.confirm(id))).data
  },
  async abandonCheckoutSession(id: string): Promise<CheckoutSession> {
    if (isMockMode) return mockAbandonCheckoutSession(id)
    return (await http.post<CheckoutSession>(checkoutSessionPaths.abandon(id))).data
  },
  async getOrder(orderId: string): Promise<TicketOrder> {
    if (isMockMode) return mockGetOrder(orderId)
    return (await http.get<TicketOrder>('/orders/' + orderId)).data
  },
  async payOrder(orderId: string): Promise<PaymentStartResult> {
    if (isMockMode) return mockPayOrder(orderId)
    return (await http.post<PaymentStartResult>('/orders/' + orderId + '/pay')).data
  },
  async getPaymentAttempt(attemptId: string): Promise<PaymentAttempt> {
    if (isMockMode) return mockGetPaymentAttempt(attemptId)
    return (await http.get<PaymentAttempt>('/payment-attempts/' + attemptId)).data
  },
  async getNotifications(): Promise<UserNotification[]> {
    if (isMockMode) return mockGetNotifications()
    return (await http.get<UserNotification[]>('/notifications')).data
  },
  async markNotificationRead(notificationId: string): Promise<UserNotification> {
    if (isMockMode) return mockMarkNotificationRead(notificationId)
    return (await http.post<UserNotification>('/notifications/' + notificationId + '/read')).data
  },
  async cancelOrder(orderId: string): Promise<TicketOrder> {
    if (isMockMode) return mockCancelOrder(orderId)
    return (await http.post<TicketOrder>('/orders/' + orderId + '/cancel')).data
  },
  async expireOrderForDemo(orderId: string): Promise<TicketOrder> {
    if (!isMockMode) throw new TicketApiError('真实 API 模式不支持模拟超时。', 'MOCK_ONLY')
    return mockExpireOrder(orderId)
  },
}

export function resetMockData() {
  seatsBySession = new Map()
  reservations = new Map()
  orders = new Map()
  checkoutSessions = new Map()
  checkoutConfirmations = new Map()
  paymentAttempts = new Map()
  notifications = []
  sequence = 24082600
  mockPaymentDelayMilliseconds = null
  mockPaymentOutcome = null
}

export function setMockLatency(milliseconds: number) {
  mockLatency = milliseconds
}

export function setMockPaymentSimulation(options: {
  delayMilliseconds: number
  outcome: 'SUCCESS' | 'FAILURE'
}) {
  mockPaymentDelayMilliseconds = options.delayMilliseconds
  mockPaymentOutcome = options.outcome
}

