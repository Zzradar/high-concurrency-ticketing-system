<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bell, ChevronDown, CircleUserRound, Database, TicketCheck } from '@lucide/vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { authState } from './auth/authState'
import { isMockMode, ticketApi } from './api/ticketApi'
import { routeNames } from './navigation'
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

async function refreshNotifications() {
  if (!authState.currentUser.value) {
    notifications.value = []
    return
  }
  try {
    notifications.value = await ticketApi.getNotifications()
  } catch {
    // Notifications are only signals; route pages re-fetch authoritative state.
  }
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
  accountOpen.value = false
  await authState.logout()
  notifications.value = []
  notificationsOpen.value = false
  await router.push({ name: routeNames.login })
}

function handleNotice(event: Event) {
  notice.value = (event as CustomEvent<string>).detail
  if (noticeTimer !== null) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => (notice.value = ''), 3600)
}

function handleFocus() {
  void refreshNotifications()
}

watch(() => authState.currentUser.value?.id, () => void refreshNotifications())

onMounted(() => {
  document.addEventListener('click', closeAccountOutside)
  document.addEventListener('keydown', closeAccountOnEscape)
  void authState.refreshMe().then(refreshNotifications)
  window.addEventListener('focus', handleFocus)
  window.addEventListener('ticketing:notice', handleNotice)
  window.addEventListener('ticketing:refresh-notifications', handleFocus)
  notificationTimer = window.setInterval(() => void refreshNotifications(), 5000)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeAccountOutside)
  document.removeEventListener('keydown', closeAccountOnEscape)
  window.removeEventListener('focus', handleFocus)
  window.removeEventListener('ticketing:notice', handleNotice)
  window.removeEventListener('ticketing:refresh-notifications', handleFocus)
  if (notificationTimer !== null) window.clearInterval(notificationTimer)
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
              <RouterLink :to="{ name: routeNames.orders }" @click="accountOpen = false">我的订单</RouterLink>
              <button type="button" @click="logout">退出登录</button>
            </nav>
          </section>
        </div>
      </div>
    </header>
    <RouterView />
    <Transition name="toast"><div v-if="notice" class="toast-message" role="status"><TicketCheck :size="18" />{{ notice }}</div></Transition>
    <footer class="site-footer"><span>票迹 Ticket Trace · 高并发票务预订系统 MVP</span><span>正式座位状态由服务端与 PostgreSQL 事务保证</span></footer>
  </div>
</template>
