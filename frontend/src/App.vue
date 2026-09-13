<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bell, ChevronDown, CircleUserRound, Database, TicketCheck } from '@lucide/vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { authState } from './auth/authState'
import { isMockMode, ticketApi, TicketApiError } from './api/ticketApi'
import { routeNames } from './navigation'
import { SingleFlight } from './utils/singleFlight'
import { nextPollDelay } from './utils/pollingPolicy'
import type { UserNotification } from './types'

const router = useRouter()
const notifications = ref<UserNotification[]>([])
const notificationsOpen = ref(false)
const accountOpen = ref(false)
const accountCenter = ref<HTMLElement | null>(null)
const accountTrigger = ref<HTMLButtonElement | null>(null)
const activeSection = computed(() => {
  const name = router.currentRoute.value.name
  if ([routeNames.events, routeNames.eventSessions, routeNames.sessionSeats].some((item) => item === name)) return 'events'
  if ([routeNames.orders, routeNames.orderDetail].some((item) => item === name)) return 'orders'
  return ''
})

function toggleAccount() {
  accountOpen.value = !accountOpen.value
  notificationsOpen.value = false
}

function toggleNotifications() {
  notificationsOpen.value = !notificationsOpen.value
  accountOpen.value = false
  if (notificationsOpen.value) void refreshNotifications()
}

function closeAccountOutside(event: Event) {
  if (event.target instanceof Node && !accountCenter.value?.contains(event.target)) accountOpen.value = false
}

function closeAccountOnEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && accountOpen.value) {
    accountOpen.value = false
    accountTrigger.value?.focus()
  }
}

watch(() => router.currentRoute.value.fullPath, () => { accountOpen.value = false })
const notice = ref('')
let notificationTimer: number | null = null
let noticeTimer: number | null = null

const unreadCount = computed(() => notifications.value.filter((item) => !item.readAt).length)

const notificationReads = new SingleFlight<void>()
let notificationEpoch = 0
let notificationDisposed = false
let loggingOut = false
let notificationWasHidden = document.hidden
let lastActivation = -Infinity
let notificationSignature: string | undefined
let notificationEmpty = 0
let notificationErrors = 0
let notificationRetry: number | undefined

function clearNotificationTimer() {
  if (notificationTimer !== null) window.clearTimeout(notificationTimer)
  notificationTimer = null
}
function invalidateNotifications() {
  notificationEpoch++
  clearNotificationTimer()
}
async function refreshNotifications() {
  const epoch = notificationEpoch, userId = authState.currentUser.value?.id
  const current = () => !notificationDisposed && !loggingOut && !document.hidden && !!userId &&
    epoch === notificationEpoch && userId === authState.currentUser.value?.id
  if (!current()) return
  clearNotificationTimer()
  await notificationReads.run(`${epoch}:${userId}`, async () => {
    try {
      const value = await ticketApi.getNotifications()
      if (!current()) return
      const signature = JSON.stringify(value.map(item => [item.id, item.readAt ?? null]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))))
      notificationEmpty = signature === notificationSignature ? Math.min(6, notificationEmpty + 1) : 0
      notificationSignature = signature
      notificationErrors = 0; notificationRetry = undefined
      notifications.value = value
    } catch (cause) {
      if (!current()) return
      notificationErrors = Math.min(5, notificationErrors + 1)
      notificationRetry = cause instanceof TicketApiError ? cause.retryAfterMs : undefined
      // Notifications are only signals; their failure never blocks navigation.
    } finally {
      if (current()) notificationTimer = window.setTimeout(() => void refreshNotifications(), nextPollDelay({
        emptyStreak: notificationEmpty, errorStreak: notificationErrors, retryAfterMs: notificationRetry,
      }, Math.random, { baseMs: 30000, maxMs: 60000 }))
    }
  }, current)
}

async function openNotification(notification: UserNotification) {
  try {
    if (!notification.readAt) await ticketApi.markNotificationRead(notification.id)
  } finally {
    notificationsOpen.value = false
    await router.push({ name: routeNames.orderDetail, params: { orderId: notification.orderId } })
  }
}

async function logout() {
  loggingOut = true
  invalidateNotifications()
  notifications.value = []
  notificationsOpen.value = false
  accountOpen.value = false
  const result = await authState.logout()
  if (notificationDisposed || authState.currentUser.value) return
  notifications.value = []
  notificationsOpen.value = false
  await router.replace({ name: routeNames.login })
  if (!result.confirmed) {
    window.dispatchEvent(new CustomEvent('ticketing:notice', { detail: '退出请求未确认，请检查网络后重试' }))
  }
}

function handleNotice(event: Event) {
  notice.value = (event as CustomEvent<string>).detail
  if (noticeTimer !== null) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => (notice.value = ''), 3600)
}

function handleFocus() {
  if (document.hidden || notificationDisposed || loggingOut) return
  notificationWasHidden = false
  // A page's authority read may emit its notification signal after focus completes.
  if (Date.now() - lastActivation < 500) return
  lastActivation = Date.now()
  void refreshNotifications()
}
function notificationVisibility() {
  if (document.hidden) {
    notificationWasHidden = true
    lastActivation = -Infinity
    invalidateNotifications()
  } else if (notificationWasHidden) handleFocus()
}
function notificationBlur() { lastActivation = -Infinity }
function notificationSignal() {
  if (Date.now() - lastActivation < 500) return
  void refreshNotifications()
}
watch(() => authState.currentUser.value?.id, () => {
  invalidateNotifications()
  notifications.value = []
  notificationSignature = undefined
  notificationEmpty = 0; notificationErrors = 0; notificationRetry = undefined
  lastActivation = -Infinity; loggingOut = false
  void refreshNotifications()
}, { immediate: true })

onMounted(() => {
  document.addEventListener('click', closeAccountOutside)
  document.addEventListener('keydown', closeAccountOnEscape)
  void authState.refreshMe().catch(() => { /* Authentication failure is handled by the auth state. */ })
  window.addEventListener('focus', handleFocus)
  window.addEventListener('blur', notificationBlur)
  window.addEventListener('ticketing:notice', handleNotice)
  window.addEventListener('ticketing:refresh-notifications', notificationSignal)
  document.addEventListener('visibilitychange', notificationVisibility)
})

onBeforeUnmount(() => {
  notificationDisposed = true
  invalidateNotifications()
  document.removeEventListener('click', closeAccountOutside)
  document.removeEventListener('keydown', closeAccountOnEscape)
  window.removeEventListener('focus', handleFocus)
  window.removeEventListener('blur', notificationBlur)
  window.removeEventListener('ticketing:notice', handleNotice)
  window.removeEventListener('ticketing:refresh-notifications', notificationSignal)
  document.removeEventListener('visibilitychange', notificationVisibility)
  if (noticeTimer !== null) window.clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="app-shell">
    <header class="site-header">
      <RouterLink class="brand" :to="{ name: routeNames.events }" aria-label="返回活动首页">
        <span class="brand__mark"><TicketCheck :size="21" aria-hidden="true" /></span>
        <span><strong>票迹</strong><small>TICKET TRACE</small></span>
      </RouterLink>
      <nav class="progress-nav" aria-label="主要导航">
        <RouterLink :class="{ 'is-active': activeSection === 'events' }" :aria-current="activeSection === 'events' ? 'page' : undefined" :to="{ name: routeNames.events }">活动</RouterLink>
        <RouterLink v-if="authState.currentUser.value" :class="{ 'is-active': activeSection === 'orders' }" :aria-current="activeSection === 'orders' ? 'page' : undefined" :to="{ name: routeNames.orders }">我的订单</RouterLink>
      </nav>
      <div class="header-actions">
        <span v-if="isMockMode" class="mode-badge"><Database :size="14" />演示数据</span>
        <div v-if="authState.currentUser.value" class="notification-center">
          <button class="notification-button" type="button" aria-label="通知中心" :aria-expanded="notificationsOpen" @click="toggleNotifications">
            <Bell :size="19" /><span v-if="unreadCount" class="notification-count">{{ unreadCount }}</span>
          </button>
          <section v-if="notificationsOpen" class="notification-panel" aria-label="通知列表">
            <header><strong>通知</strong><span>{{ unreadCount }} 条未读</span></header>
            <p v-if="!notifications.length" class="notification-empty">暂无通知</p>
            <button v-for="item in notifications" :key="item.id" :class="['notification-item', { 'is-read': item.readAt }]" type="button" @click="openNotification(item)">
              <strong>{{ item.title }}</strong><span>{{ item.message }}</span><small>{{ new Date(item.createdAt).toLocaleString('zh-CN') }}</small>
            </button>
          </section>
        </div>
        <RouterLink v-if="!authState.currentUser.value" class="user-button" :to="{ name: routeNames.login }">登录</RouterLink>
        <div v-else ref="accountCenter" class="account-center">
          <button ref="accountTrigger" class="user-button" type="button" aria-label="账户菜单" aria-haspopup="true" :aria-expanded="accountOpen" aria-controls="account-panel" @click="toggleAccount">
            <CircleUserRound :size="20" aria-hidden="true" /><span>{{ authState.currentUser.value.displayName }}</span><ChevronDown :size="14" aria-hidden="true" />
          </button>
          <section v-if="accountOpen" id="account-panel" class="account-panel" aria-label="当前账户">
            <header><strong>{{ authState.currentUser.value.displayName }}</strong><small>{{ authState.currentUser.value.username }}</small></header>
            <nav aria-label="账户操作">
              <RouterLink v-if="authState.currentUser.value.role === 'ADMIN'" to="/admin" @click="accountOpen = false">管理后台</RouterLink>
              <RouterLink :to="{ name: routeNames.orders }" @click="accountOpen = false">我的订单</RouterLink>
              <button type="button" @click="logout">退出登录</button>
            </nav>
          </section>
        </div>
      </div>
    </header>
    <RouterView />
    <Transition name="toast"><div v-if="notice" class="toast-message" role="status"><TicketCheck :size="18" />{{ notice }}</div></Transition>
    <footer class="site-footer"><span>票迹 Ticket Trace</span><span>发现活动 · 选择场次 · 在线选座</span></footer>
  </div>
</template>
