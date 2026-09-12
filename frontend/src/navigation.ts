export const routeNames = {
  home: 'home',
  login: 'login',
  events: 'events',
  eventSessions: 'event-sessions',
  sessionSeats: 'session-seats',
  waitingRoom: 'waiting-room',
  orders: 'orders',
  orderDetail: 'order-detail',
  notFound: 'not-found',
} as const

export function setPageTitle(title: string) {
  document.title = title + ' | 票迹'
}
