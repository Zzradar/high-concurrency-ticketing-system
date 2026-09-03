import { createRouter, createWebHistory } from 'vue-router'
import { authState } from './auth/authState'
import EventListPage from './pages/EventListPage.vue'
import LoginView from './pages/LoginView.vue'
import OrderListPage from './pages/OrderListPage.vue'
import OrderPage from './pages/OrderPage.vue'
import SeatSelectionPage from './pages/SeatSelectionPage.vue'
import SessionListPage from './pages/SessionListPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/events' },
    { path: '/login', component: LoginView },
    { path: '/events', component: EventListPage },
    { path: '/events/:eventId/sessions', component: SessionListPage },
    { path: '/sessions/:sessionId/seats', component: SeatSelectionPage },
    { path: '/orders', component: OrderListPage, meta: { requiresAuth: true } },
    { path: '/orders/:orderId', component: OrderPage, meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', redirect: '/events' },
  ],
})

router.beforeEach(async (to) => {
  const user = await authState.ensureAuthLoaded()
  if (to.meta.requiresAuth && !user) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && user) return '/events'
})
