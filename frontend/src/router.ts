import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import { authState } from './auth/authState'
import { routeNames } from './navigation'
import { cleanPaymentQuery, hasStripeQuery } from './payments/paymentReturn'
import EventListPage from './pages/EventListPage.vue'
import LoginView from './pages/LoginView.vue'
import NotFoundPage from './pages/NotFoundPage.vue'
import OrderListPage from './pages/OrderListPage.vue'
import OrderPage from './pages/OrderPage.vue'
import SeatSelectionPage from './pages/SeatSelectionPage.vue'
import SessionListPage from './pages/SessionListPage.vue'

export const appRoutes: RouteRecordRaw[] = [
  {path:'/admin',name:'admin',redirect:'/admin/events',meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  {path:'/admin/events',name:'admin-events',component:()=>import('./pages/AdminEventListPage.vue'),meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  {path:'/admin/events/new',name:'admin-event-new',component:()=>import('./pages/AdminEventEditorPage.vue'),meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  {path:'/admin/events/:eventId',name:'admin-event',component:()=>import('./pages/AdminEventEditorPage.vue'),meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  {path:'/admin/venues',name:'admin-venues',component:()=>import('./pages/AdminVenueListPage.vue'),meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  {path:'/admin/venues/new',name:'admin-venue-new',component:()=>import('./pages/AdminVenueEditorPage.vue'),meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  {path:'/admin/venues/:venueId',name:'admin-venue',component:()=>import('./pages/AdminVenueEditorPage.vue'),meta:{requiresAuth:true,requiresAdmin:true,title:'管理后台 | 票迹'}},
  { path: '/', name: routeNames.home, redirect: { name: routeNames.events } },
  { path: '/login', name: routeNames.login, component: LoginView, meta: { title: '登录 | 票迹' } },
  { path: '/events', name: routeNames.events, component: EventListPage, meta: { title: '活动列表 | 票迹' } },
  {
    path: '/events/:eventId/sessions',
    name: routeNames.eventSessions,
    component: SessionListPage,
    meta: { title: '场次 | 票迹' },
  },
  {
    path: '/sessions/:sessionId/seats',
    name: routeNames.sessionSeats,
    component: SeatSelectionPage,
    meta: { title: '选座 | 票迹' },
  },
  {
    path: '/orders',
    name: routeNames.orders,
    component: OrderListPage,
    meta: { requiresAuth: true, title: '我的订单 | 票迹' },
  },
  {
    path: '/orders/:orderId',
    name: routeNames.orderDetail,
    component: OrderPage,
    meta: { requiresAuth: true, title: '订单详情 | 票迹' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: routeNames.notFound,
    component: NotFoundPage,
    meta: { title: '页面不存在 | 票迹' },
  },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const appRouter = createRouter({
    history,
    routes: appRoutes,
    scrollBehavior(_to, _from, savedPosition) {
      return savedPosition ?? { top: 0 }
    },
  })

  appRouter.beforeEach(async (to) => {
    // Strip provider parameters before auth can copy fullPath into a login redirect.
    if (hasStripeQuery(to.query)) {
      return { path: to.path, query: cleanPaymentQuery(to.query, false), hash: to.hash, replace: true }
    }
    const user = await authState.ensureAuthLoaded()
    if (to.meta.requiresAuth && !user) {
      return { name: routeNames.login, query: { redirect: to.fullPath } }
    }
    if (to.meta.requiresAdmin && user?.role !== 'ADMIN') return { name: routeNames.events }
    if (to.name === routeNames.login && user) return { name: routeNames.events }
  })

  appRouter.afterEach((to) => {
    document.title = typeof to.meta.title === 'string' ? to.meta.title : '票迹'
  })

  return appRouter
}

export const router = createAppRouter()
