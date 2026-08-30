<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertCircle, CircleUserRound, Database, TicketCheck, X } from '@lucide/vue'
import { isMockMode, TicketApiError, ticketApi } from './api/ticketApi'
import EventListView from './views/EventListView.vue'
import OrderView from './views/OrderView.vue'
import SeatSelectionView from './views/SeatSelectionView.vue'
import SessionListView from './views/SessionListView.vue'
import type { Seat, TicketEvent, TicketOrder, TicketSession, ViewName } from './types'

const currentView = ref<ViewName>('event-list')
const events = ref<TicketEvent[]>([])
const sessions = ref<TicketSession[]>([])
const seats = ref<Seat[]>([])
const selectedSeatIds = ref<string[]>([])
const currentEvent = ref<TicketEvent | null>(null)
const currentSession = ref<TicketSession | null>(null)
const currentOrder = ref<TicketOrder | null>(null)
const loading = ref(true)
const busy = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

const selectedSeats = computed(() =>
  seats.value.filter((seat) => selectedSeatIds.value.includes(seat.id)),
)

const steps = [
  { key: 'event-list', label: '活动' },
  { key: 'session-list', label: '场次' },
  { key: 'seat-selection', label: '选座' },
  { key: 'order', label: '订单' },
] as const

const currentStepIndex = computed(() =>
  steps.findIndex((step) => step.key === currentView.value),
)

function showError(error: unknown, fallback: string) {
  if (error instanceof TicketApiError) {
    errorMessage.value = error.message
  } else {
    errorMessage.value = fallback
  }
}

function showNotice(message: string) {
  noticeMessage.value = message
  window.setTimeout(() => {
    if (noticeMessage.value === message) noticeMessage.value = ''
  }, 3200)
}

async function loadEvents() {
  loading.value = true
  errorMessage.value = ''
  try {
    events.value = await ticketApi.getEvents()
  } catch (error) {
    showError(error, '活动加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

async function chooseEvent(event: TicketEvent) {
  currentEvent.value = event
  currentView.value = 'session-list'
  loading.value = true
  errorMessage.value = ''
  try {
    sessions.value = await ticketApi.getSessions(event.id)
  } catch (error) {
    showError(error, '场次加载失败，请返回后重试。')
  } finally {
    loading.value = false
  }
}

async function chooseSession(session: TicketSession) {
  currentSession.value = session
  currentView.value = 'seat-selection'
  selectedSeatIds.value = []
  loading.value = true
  errorMessage.value = ''
  try {
    seats.value = await ticketApi.getSeats(session.id)
  } catch (error) {
    showError(error, '座位图加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function toggleSeat(seat: Seat) {
  if (seat.status !== 'AVAILABLE') return

  if (selectedSeatIds.value.includes(seat.id)) {
    selectedSeatIds.value = selectedSeatIds.value.filter((id) => id !== seat.id)
    return
  }

  if (selectedSeatIds.value.length >= 6) {
    errorMessage.value = '每个订单最多选择 6 个座位。'
    return
  }

  errorMessage.value = ''
  selectedSeatIds.value = [...selectedSeatIds.value, seat.id]
}

async function refreshSeats(preserveError = false) {
  if (!currentSession.value) return
  const preservedError = preserveError ? errorMessage.value : ''
  loading.value = true
  if (!preserveError) errorMessage.value = ''
  try {
    seats.value = await ticketApi.getSeats(currentSession.value.id)
    const selectableIds = new Set(
      seats.value.filter((seat) => seat.status === 'AVAILABLE').map((seat) => seat.id),
    )
    selectedSeatIds.value = selectedSeatIds.value.filter((id) => selectableIds.has(id))
    showNotice('座位状态已更新')
  } catch (error) {
    showError(error, '座位状态刷新失败，请稍后重试。')
  } finally {
    if (preservedError) errorMessage.value = preservedError
    loading.value = false
  }
}

async function submitReservation() {
  if (!currentSession.value || !selectedSeatIds.value.length) return
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await ticketApi.createReservation(
      currentSession.value.id,
      selectedSeatIds.value,
    )
    currentOrder.value = result.order
    seats.value = await ticketApi.getSeats(currentSession.value.id)
    currentView.value = 'order'
    showNotice('座位锁定成功，请在 15 分钟内支付')
  } catch (error) {
    showError(error, '预订提交失败，请刷新座位后重试。')
    await refreshSeats(true)
  } finally {
    busy.value = false
  }
}

async function refreshOrder(preserveError = false) {
  if (!currentOrder.value) return
  const preservedError = preserveError ? errorMessage.value : ''
  busy.value = true
  if (!preserveError) errorMessage.value = ''
  try {
    currentOrder.value = await ticketApi.getOrder(currentOrder.value.id)
    if (currentSession.value) {
      seats.value = await ticketApi.getSeats(currentSession.value.id)
    }
  } catch (error) {
    showError(error, '订单状态查询失败，请稍后重试。')
  } finally {
    if (preservedError) errorMessage.value = preservedError
    busy.value = false
  }
}

async function payOrder() {
  if (!currentOrder.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    currentOrder.value = await ticketApi.payOrder(currentOrder.value.id)
    if (currentSession.value) seats.value = await ticketApi.getSeats(currentSession.value.id)
    showNotice('支付成功，订单与座位状态已同步确认')
  } catch (error) {
    showError(error, '支付请求结果未知，正在重新查询订单。')
    await refreshOrder(true)
  } finally {
    busy.value = false
  }
}

async function cancelOrder() {
  if (!currentOrder.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    currentOrder.value = await ticketApi.cancelOrder(currentOrder.value.id)
    if (currentSession.value) seats.value = await ticketApi.getSeats(currentSession.value.id)
    showNotice('订单已取消，座位已释放')
  } catch (error) {
    showError(error, '取消订单失败，请刷新订单状态。')
  } finally {
    busy.value = false
  }
}

async function expireOrder() {
  if (!currentOrder.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    currentOrder.value = await ticketApi.expireOrderForDemo(currentOrder.value.id)
    if (currentSession.value) seats.value = await ticketApi.getSeats(currentSession.value.id)
    showNotice('服务端已将订单标记为过期并释放座位')
  } catch (error) {
    showError(error, '模拟超时失败。')
  } finally {
    busy.value = false
  }
}

function backToEvents() {
  currentView.value = 'event-list'
  currentEvent.value = null
  currentSession.value = null
  currentOrder.value = null
  sessions.value = []
  seats.value = []
  selectedSeatIds.value = []
  errorMessage.value = ''
}

function backToSessions() {
  currentView.value = 'session-list'
  currentSession.value = null
  currentOrder.value = null
  seats.value = []
  selectedSeatIds.value = []
  errorMessage.value = ''
}

onMounted(loadEvents)
</script>

<template>
  <div class="app-shell">
    <header class="site-header">
      <button class="brand" type="button" aria-label="返回活动首页" @click="backToEvents">
        <span class="brand__mark"><TicketCheck :size="21" aria-hidden="true" /></span>
        <span><strong>票迹</strong><small>TICKET TRACE</small></span>
      </button>

      <nav class="progress-nav" aria-label="购票进度">
        <template v-for="(step, index) in steps" :key="step.key">
          <div
            :class="[
              'progress-step',
              { 'is-active': index === currentStepIndex, 'is-complete': index < currentStepIndex },
            ]"
          >
            <span>{{ index < currentStepIndex ? '✓' : index + 1 }}</span>
            <strong>{{ step.label }}</strong>
          </div>
          <i v-if="index < steps.length - 1" :class="{ 'is-complete': index < currentStepIndex }"></i>
        </template>
      </nav>

      <div class="header-actions">
        <span v-if="isMockMode" class="mode-badge">
          <Database :size="14" aria-hidden="true" />
          演示数据
        </span>
        <button class="user-button" type="button" aria-label="当前用户 U-1001">
          <CircleUserRound :size="20" aria-hidden="true" />
          <span>U-1001</span>
        </button>
      </div>
    </header>

    <div v-if="errorMessage" class="message-banner message-banner--error" role="alert">
      <AlertCircle :size="19" aria-hidden="true" />
      <span>{{ errorMessage }}</span>
      <button type="button" aria-label="关闭错误提示" @click="errorMessage = ''">
        <X :size="17" aria-hidden="true" />
      </button>
    </div>

    <EventListView
      v-if="currentView === 'event-list'"
      :events="events"
      :loading="loading"
      @select="chooseEvent"
    />
    <SessionListView
      v-else-if="currentView === 'session-list' && currentEvent"
      :event="currentEvent"
      :sessions="sessions"
      :loading="loading"
      @back="backToEvents"
      @select="chooseSession"
    />
    <SeatSelectionView
      v-else-if="currentView === 'seat-selection' && currentEvent && currentSession"
      :event="currentEvent"
      :session="currentSession"
      :seats="seats"
      :selected-seats="selectedSeats"
      :selected-seat-ids="selectedSeatIds"
      :loading="loading"
      :busy="busy"
      @back="backToSessions"
      @toggle="toggleSeat"
      @reserve="submitReservation"
      @refresh="refreshSeats"
      @clear="selectedSeatIds = []"
    />
    <OrderView
      v-else-if="currentView === 'order' && currentEvent && currentSession && currentOrder"
      :order="currentOrder"
      :event="currentEvent"
      :session="currentSession"
      :seats="seats"
      :busy="busy"
      @pay="payOrder"
      @cancel="cancelOrder"
      @expire="expireOrder"
      @refresh="refreshOrder"
      @start-over="backToEvents"
    />

    <Transition name="toast">
      <div v-if="noticeMessage" class="toast-message" role="status">
        <TicketCheck :size="18" aria-hidden="true" />
        {{ noticeMessage }}
      </div>
    </Transition>

    <footer class="site-footer">
      <span>票迹 Ticket Trace · 高并发票务预订系统 MVP</span>
      <span>正式座位状态由服务端与 PostgreSQL 事务保证</span>
    </footer>
  </div>
</template>
