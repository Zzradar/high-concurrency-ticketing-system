<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bell, CircleUserRound, Database, TicketCheck } from '@lucide/vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { authState } from './auth/authState'
import { isMockMode, ticketApi } from './api/ticketApi'
import type { UserNotification } from './types'

const router = useRouter()
const notifications = ref<UserNotification[]>([])
const notificationsOpen = ref(false)
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
    await router.push(`/orders/${notification.orderId}`)
  }
}

async function logout() {
  await authState.logout()
  notifications.value = []
  await router.push('/login')
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
  void authState.refreshMe().then(refreshNotifications)
  window.addEventListener('focus', handleFocus)
  window.addEventListener('ticketing:notice', handleNotice)
  window.addEventListener('ticketing:refresh-notifications', handleFocus)
  notificationTimer = window.setInterval(() => void refreshNotifications(), 5000)
})

onBeforeUnmount(() => {
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
      <RouterLink class="brand" to="/events" aria-label="返回活动首页">
        <span class="brand__mark"><TicketCheck :size="21" aria-hidden="true" /></span>
        <span><strong>票迹</strong><small>TICKET TRACE</small></span>
      </RouterLink>
      <nav class="progress-nav" aria-label="主要导航">
        <RouterLink to="/events">活动</RouterLink>
        <RouterLink v-if="authState.currentUser.value" to="/orders">我的订单</RouterLink>
      </nav>
      <div class="header-actions">
        <span v-if="isMockMode" class="mode-badge"><Database :size="14" />演示数据</span>
        <div v-if="authState.currentUser.value" class="notification-center">
          <button class="notification-button" type="button" aria-label="通知中心" @click="notificationsOpen = !notificationsOpen">
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
        <RouterLink v-if="!authState.currentUser.value" class="user-button" to="/login">登录</RouterLink>
        <button v-else class="user-button" type="button" @click="logout">
          <CircleUserRound :size="20" /><span>{{ authState.currentUser.value.displayName }}</span><small>退出</small>
        </button>
      </div>
    </header>
    <RouterView />
    <Transition name="toast"><div v-if="notice" class="toast-message" role="status"><TicketCheck :size="18" />{{ notice }}</div></Transition>
    <footer class="site-footer"><span>票迹 Ticket Trace · 高并发票务预订系统 MVP</span><span>正式座位状态由服务端与 PostgreSQL 事务保证</span></footer>
  </div>
</template>
