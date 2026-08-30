import axios from 'axios'
import type {
  Reservation,
  ReservationResult,
  Seat,
  TicketEvent,
  TicketOrder,
  TicketSession,
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

export const isMockMode = import.meta.env.VITE_USE_MOCK_API !== 'false'

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
let sequence = 24082600

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

function synchronizeExpiry(order: TicketOrder) {
  if (order.status === 'PENDING_PAYMENT' && Date.parse(order.expiresAt) <= Date.now()) {
    releaseReservation(order, 'EXPIRED')
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

async function mockGetOrder(orderId: string) {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  synchronizeExpiry(order)
  return clone(order)
}

async function mockPayOrder(orderId: string) {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  synchronizeExpiry(order)
  if (order.status !== 'PENDING_PAYMENT') {
    throw new TicketApiError('订单已过期或无法支付，请刷新订单状态。', 'ORDER_NOT_PAYABLE')
  }

  order.status = 'PAID'
  order.paidAt = new Date().toISOString()
  const reservation = reservations.get(order.reservationId)
  if (reservation) reservation.status = 'CONFIRMED'
  ensureSeats(order.sessionId).forEach((seat) => {
    if (order.seatIds.includes(seat.id)) seat.status = 'SOLD'
  })
  return clone(order)
}

async function mockCancelOrder(orderId: string) {
  await wait()
  const order = orders.get(orderId)
  if (!order) throw new TicketApiError('未找到该订单。', 'ORDER_NOT_FOUND')
  synchronizeExpiry(order)
  if (order.status !== 'PENDING_PAYMENT') {
    throw new TicketApiError('当前订单无法取消。', 'ORDER_NOT_CANCELLABLE')
  }
  releaseReservation(order, 'CANCELLED')
  return clone(order)
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

export const ticketApi = {
  async getEvents(): Promise<TicketEvent[]> {
    if (isMockMode) return mockGetEvents()
    return (await http.get<TicketEvent[]>('/events')).data
  },
  async getSessions(eventId: string): Promise<TicketSession[]> {
    if (isMockMode) return mockGetSessions(eventId)
    return (await http.get<TicketSession[]>('/events/' + eventId + '/sessions')).data
  },
  async getSeats(sessionId: string): Promise<Seat[]> {
    if (isMockMode) return mockGetSeats(sessionId)
    return (await http.get<Seat[]>('/sessions/' + sessionId + '/seats')).data
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
  async getOrder(orderId: string): Promise<TicketOrder> {
    if (isMockMode) return mockGetOrder(orderId)
    return (await http.get<TicketOrder>('/orders/' + orderId)).data
  },
  async payOrder(orderId: string): Promise<TicketOrder> {
    if (isMockMode) return mockPayOrder(orderId)
    return (await http.post<TicketOrder>('/orders/' + orderId + '/pay')).data
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
  sequence = 24082600
}

export function setMockLatency(milliseconds: number) {
  mockLatency = milliseconds
}

