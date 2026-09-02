<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertCircle, CircleUserRound, Database, TicketCheck, X } from '@lucide/vue'
import { isMockMode, TicketApiError, ticketApi } from './api/ticketApi'
import EventListView from './views/EventListView.vue'
import OrderView from './views/OrderView.vue'
import SeatSelectionView from './views/SeatSelectionView.vue'
import SessionListView from './views/SessionListView.vue'
import type {
  CheckoutSession,
  Seat,
  TicketEvent,
  TicketOrder,
  TicketSession,
  ViewName,
} from './types'

const CHECKOUT_LOCATOR_KEY = 'ticketing.currentCheckoutSession'
const SUBMITTING_POLL_INTERVAL_MS = 2000
const SUBMITTING_POLL_LIMIT_MS = 15000

const currentView = ref<ViewName>('event-list')
const events = ref<TicketEvent[]>([])
const sessions = ref<TicketSession[]>([])
const seats = ref<Seat[]>([])
const selectedSeatIds = ref<string[]>([])
const currentEvent = ref<TicketEvent | null>(null)
const currentSession = ref<TicketSession | null>(null)
const currentOrder = ref<TicketOrder | null>(null)
const currentCheckoutSession = ref<CheckoutSession | null>(null)
const recoverableCheckoutSessions = ref<CheckoutSession[]>([])
const loading = ref(true)
const busy = ref(false)
const checkoutCreating = ref(false)
const checkoutSyncInFlight = ref(false)
const confirming = ref(false)
const submittingPolling = ref(false)
const submitUncertain = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

let checkoutCreationPromise: Promise<CheckoutSession | null> | null = null
let checkoutSyncPromise: Promise<void> | null = null
let submittingPollTimer: number | null = null
let submittingPollGeneration = 0

const selectedSeats = computed(() =>
  seats.value.filter((seat) => selectedSeatIds.value.includes(seat.id)),
)

const checkoutEditingDisabled = computed(
  () =>
    confirming.value ||
    submittingPolling.value ||
    submitUncertain.value ||
    currentCheckoutSession.value?.status === 'SUBMITTING' ||
    currentCheckoutSession.value?.status === 'RESERVED' ||
    currentCheckoutSession.value?.status === 'ABANDONED',
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

function sameSeatSet(left: string[], right: string[]) {
  return [...left].sort().join('\n') === [...right].sort().join('\n')
}

function writeCheckoutLocator(checkout: CheckoutSession) {
  sessionStorage.setItem(
    CHECKOUT_LOCATOR_KEY,
    JSON.stringify({ checkoutSessionId: checkout.id, sessionId: checkout.sessionId }),
  )
}

function clearCheckoutLocator(checkoutId?: string) {
  if (checkoutId) {
    try {
      const value = JSON.parse(sessionStorage.getItem(CHECKOUT_LOCATOR_KEY) ?? '{}') as {
        checkoutSessionId?: string
      }
      if (value.checkoutSessionId !== checkoutId) return
    } catch {
      // Invalid locator is cleared below.
    }
  }
  sessionStorage.removeItem(CHECKOUT_LOCATOR_KEY)
}

function stopSubmittingPolling() {
  submittingPollGeneration += 1
  if (submittingPollTimer !== null) window.clearTimeout(submittingPollTimer)
  submittingPollTimer = null
  submittingPolling.value = false
}

function waitForSubmittingPoll(milliseconds: number) {
  return new Promise<void>((resolve) => {
    submittingPollTimer = window.setTimeout(() => {
      submittingPollTimer = null
      resolve()
    }, milliseconds)
  })
}

function applyCheckoutCheckpoint(checkout: CheckoutSession) {
  currentCheckoutSession.value = checkout
  selectedSeatIds.value = [...checkout.seatIds]
  writeCheckoutLocator(checkout)
}

async function enterReservedCheckout(checkout: CheckoutSession) {
  stopSubmittingPolling()
  submitUncertain.value = false
  currentCheckoutSession.value = checkout
  writeCheckoutLocator(checkout)
  if (!checkout.order) {
    errorMessage.value = '购票会话已确认，但订单详情暂时不可用，请稍后重试。'
    return
  }
  currentOrder.value = checkout.order
  if (currentSession.value) seats.value = await ticketApi.getSeats(currentSession.value.id)
  currentView.value = 'order'
  showNotice('座位锁定成功，请在 15 分钟内支付')
}

async function observeCheckoutState(checkout: CheckoutSession) {
  currentCheckoutSession.value = checkout
  writeCheckoutLocator(checkout)
  if (checkout.status === 'RESERVED') {
    await enterReservedCheckout(checkout)
    return true
  }
  if (checkout.status === 'SELECTING') {
    stopSubmittingPolling()
    submitUncertain.value = false
    selectedSeatIds.value = [...checkout.seatIds]
    return true
  }
  if (checkout.status === 'ABANDONED') {
    stopSubmittingPolling()
    submitUncertain.value = false
    selectedSeatIds.value = []
    return true
  }
  selectedSeatIds.value = [...checkout.seatIds]
  return false
}

function startSubmittingPolling(checkoutId: string) {
  stopSubmittingPolling()
  const generation = submittingPollGeneration
  submittingPolling.value = true
  submitUncertain.value = false
  void (async () => {
    const startedAt = Date.now()
    while (
      generation === submittingPollGeneration &&
      currentView.value === 'seat-selection' &&
      Date.now() - startedAt < SUBMITTING_POLL_LIMIT_MS
    ) {
      try {
        const checkout = await ticketApi.getCheckoutSession(checkoutId)
        if (generation !== submittingPollGeneration) return
        if (await observeCheckoutState(checkout)) return
      } catch {
        // A transient read failure remains an unknown result; retry until the deadline.
      }
      const remaining = SUBMITTING_POLL_LIMIT_MS - (Date.now() - startedAt)
      if (remaining <= 0) break
      await waitForSubmittingPoll(Math.min(SUBMITTING_POLL_INTERVAL_MS, remaining))
    }
    if (generation !== submittingPollGeneration) return
    submittingPolling.value = false
    submitUncertain.value = true
    errorMessage.value = '确认结果暂时无法确定，请稍后继续原确认。'
  })()
}

async function continueCheckout(checkout: CheckoutSession) {
  recoverableCheckoutSessions.value = []
  applyCheckoutCheckpoint(checkout)
  errorMessage.value = ''
  if (checkout.status === 'SUBMITTING') startSubmittingPolling(checkout.id)
  if (checkout.status === 'RESERVED') await enterReservedCheckout(checkout)
}

async function recoverCheckoutForSession(sessionId: string) {
  const rawLocator = sessionStorage.getItem(CHECKOUT_LOCATOR_KEY)
  if (rawLocator) {
    try {
      const locator = JSON.parse(rawLocator) as {
        checkoutSessionId?: string
        sessionId?: string
      }
      if (locator.sessionId === sessionId && locator.checkoutSessionId) {
        try {
          const checkout = await ticketApi.getCheckoutSession(locator.checkoutSessionId)
          if (checkout.sessionId === sessionId && checkout.status !== 'ABANDONED') {
            await continueCheckout(checkout)
            return
          }
        } catch {
          clearCheckoutLocator()
        }
      }
    } catch {
      clearCheckoutLocator()
    }
  }
  recoverableCheckoutSessions.value =
    await ticketApi.listRecoverableCheckoutSessions(sessionId)
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
  stopSubmittingPolling()
  currentSession.value = session
  currentView.value = 'seat-selection'
  selectedSeatIds.value = []
  currentCheckoutSession.value = null
  recoverableCheckoutSessions.value = []
  submitUncertain.value = false
  loading.value = true
  errorMessage.value = ''
  try {
    seats.value = await ticketApi.getSeats(session.id)
    await recoverCheckoutForSession(session.id)
  } catch (error) {
    showError(error, '座位图加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function toggleSeat(seat: Seat) {
  if (checkoutEditingDisabled.value) return
  if (selectedSeatIds.value.includes(seat.id)) {
    selectedSeatIds.value = selectedSeatIds.value.filter((id) => id !== seat.id)
    void persistSeatIntent().catch(() => undefined)
    return
  }

  if (seat.status !== 'AVAILABLE') return

  if (selectedSeatIds.value.length >= 6) {
    errorMessage.value = '每个订单最多选择 6 个座位。'
    return
  }

  errorMessage.value = ''
  selectedSeatIds.value = [...selectedSeatIds.value, seat.id]
  void persistSeatIntent().catch(() => undefined)
}

async function ensureCheckoutSession() {
  if (currentCheckoutSession.value) return currentCheckoutSession.value
  if (checkoutCreationPromise) return checkoutCreationPromise
  if (!currentSession.value || selectedSeatIds.value.length === 0) return null
  const sessionId = currentSession.value.id
  const initialSeats = [...selectedSeatIds.value]
  checkoutCreating.value = true
  checkoutCreationPromise = ticketApi
    .createCheckoutSession(sessionId, initialSeats)
    .then(async (checkout) => {
      writeCheckoutLocator(checkout)
      if (currentSession.value?.id !== sessionId || currentView.value !== 'seat-selection') {
        return null
      }
      currentCheckoutSession.value = checkout
      if (!sameSeatSet(selectedSeatIds.value, checkout.seatIds)) await ensureSeatSync()
      return currentCheckoutSession.value
    })
    .catch((error) => {
      showError(error, '选座尚未保存，请继续修改或再次提交以重试。')
      return null
    })
    .finally(() => {
      checkoutCreating.value = false
      checkoutCreationPromise = null
    })
  return checkoutCreationPromise
}

async function handleVersionConflict(checkoutId: string) {
  const latest = await ticketApi.getCheckoutSession(checkoutId)
  applyCheckoutCheckpoint(latest)
  confirming.value = false
  errorMessage.value = '该购票会话已在其他页面发生修改，请确认最新座位后重新提交。'
  if (latest.status === 'SUBMITTING') startSubmittingPolling(latest.id)
}

async function ensureSeatSync(fixedTarget?: string[]) {
  if (checkoutSyncPromise) return checkoutSyncPromise
  checkoutSyncInFlight.value = true
  checkoutSyncPromise = (async () => {
    while (true) {
      const checkout = currentCheckoutSession.value
      if (!checkout || checkout.status !== 'SELECTING') return
      const desired = [...(fixedTarget ?? selectedSeatIds.value)]
      if (sameSeatSet(desired, checkout.seatIds)) return
      try {
        const updated = await ticketApi.replaceCheckoutSessionSeats(
          checkout.id,
          desired,
          checkout.revision,
        )
        if (currentCheckoutSession.value?.id !== checkout.id) return
        currentCheckoutSession.value = updated
        writeCheckoutLocator(updated)
      } catch (error) {
        if (
          error instanceof TicketApiError &&
          error.code === 'CHECKOUT_SESSION_VERSION_CONFLICT'
        ) {
          await handleVersionConflict(checkout.id)
        } else {
          showError(error, '选座同步失败，提交前将再次重试。')
        }
        throw error
      }
    }
  })().finally(() => {
    checkoutSyncInFlight.value = false
    checkoutSyncPromise = null
  })
  return checkoutSyncPromise
}

async function persistSeatIntent() {
  if (!currentCheckoutSession.value) {
    if (selectedSeatIds.value.length > 0) await ensureCheckoutSession()
    return
  }
  if (currentCheckoutSession.value.status === 'SELECTING') await ensureSeatSync()
}

function clearSelectedSeats() {
  if (checkoutEditingDisabled.value) return
  selectedSeatIds.value = []
  void persistSeatIntent().catch(() => undefined)
}

async function refreshSeats(preserveError = false) {
  if (!currentSession.value) return
  const preservedError = preserveError ? errorMessage.value : ''
  loading.value = true
  if (!preserveError) errorMessage.value = ''
  try {
    seats.value = await ticketApi.getSeats(currentSession.value.id)
    showNotice('座位状态已更新')
  } catch (error) {
    showError(error, '座位状态刷新失败，请稍后重试。')
  } finally {
    if (preservedError) errorMessage.value = preservedError
    loading.value = false
  }
}

async function reconcileUnknownConfirmation(checkoutId: string) {
  try {
    const checkout = await ticketApi.getCheckoutSession(checkoutId)
    if (await observeCheckoutState(checkout)) return
  } catch {
    // Continue polling because the formal result remains unknown.
  }
  startSubmittingPolling(checkoutId)
}

async function submitReservation() {
  if (!currentSession.value || !selectedSeatIds.value.length) return
  confirming.value = true
  submitUncertain.value = false
  errorMessage.value = ''
  const confirmTargetSeats = [...selectedSeatIds.value]
  try {
    await ensureCheckoutSession()
    if (checkoutCreationPromise) await checkoutCreationPromise
    if (checkoutSyncPromise) await checkoutSyncPromise
    await ensureSeatSync(confirmTargetSeats)
    const checkout = currentCheckoutSession.value
    if (!checkout || !sameSeatSet(checkout.seatIds, confirmTargetSeats)) {
      throw new Error('Checkout session did not reach the final seat checkpoint')
    }
    const confirmed = await ticketApi.confirmCheckoutSession(checkout.id)
    await observeCheckoutState(confirmed)
  } catch (error) {
    const checkout = currentCheckoutSession.value
    if (
      error instanceof TicketApiError &&
      error.code === 'CHECKOUT_SESSION_VERSION_CONFLICT'
    ) {
      return
    }
    if (error instanceof TicketApiError && error.code === 'SEAT_CONFLICT' && checkout) {
      const current = await ticketApi.getCheckoutSession(checkout.id)
      applyCheckoutCheckpoint(current)
      await refreshSeats(true)
      errorMessage.value = error.message
      return
    }
    if (checkout) {
      showError(error, '确认结果暂时未知，正在查询原购票会话。')
      await reconcileUnknownConfirmation(checkout.id)
    } else {
      showError(error, '选座尚未同步，无法提交预订。')
    }
  } finally {
    confirming.value = false
  }
}

async function retryOriginalConfirmation() {
  const checkout = currentCheckoutSession.value
  if (!checkout || checkout.status !== 'SUBMITTING') return
  stopSubmittingPolling()
  submitUncertain.value = false
  confirming.value = true
  errorMessage.value = ''
  try {
    const result = await ticketApi.confirmCheckoutSession(checkout.id)
    await observeCheckoutState(result)
  } catch (error) {
    showError(error, '确认结果暂时未知，正在继续查询原购票会话。')
    await reconcileUnknownConfirmation(checkout.id)
  } finally {
    confirming.value = false
  }
}

async function abandonRecoverable(checkout: CheckoutSession) {
  try {
    await ticketApi.abandonCheckoutSession(checkout.id)
    recoverableCheckoutSessions.value = recoverableCheckoutSessions.value.filter(
      (candidate) => candidate.id !== checkout.id,
    )
    clearCheckoutLocator(checkout.id)
  } catch (error) {
    showError(error, '购票会话放弃失败，请稍后重试。')
  }
}

function startNewCheckout() {
  stopSubmittingPolling()
  if (currentCheckoutSession.value) clearCheckoutLocator(currentCheckoutSession.value.id)
  currentCheckoutSession.value = null
  recoverableCheckoutSessions.value = []
  selectedSeatIds.value = []
  submitUncertain.value = false
  errorMessage.value = ''
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
  stopSubmittingPolling()
  currentView.value = 'event-list'
  currentEvent.value = null
  currentSession.value = null
  currentOrder.value = null
  currentCheckoutSession.value = null
  recoverableCheckoutSessions.value = []
  sessions.value = []
  seats.value = []
  selectedSeatIds.value = []
  errorMessage.value = ''
}

function backToSessions() {
  stopSubmittingPolling()
  currentView.value = 'session-list'
  currentSession.value = null
  currentOrder.value = null
  currentCheckoutSession.value = null
  recoverableCheckoutSessions.value = []
  seats.value = []
  selectedSeatIds.value = []
  errorMessage.value = ''
}

onMounted(loadEvents)
onBeforeUnmount(stopSubmittingPolling)
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
      :checkout-session="currentCheckoutSession"
      :recoverable-checkout-sessions="recoverableCheckoutSessions"
      :loading="loading"
      :checkout-creating="checkoutCreating"
      :checkout-sync-in-flight="checkoutSyncInFlight"
      :confirming="confirming"
      :submitting-polling="submittingPolling"
      :submit-uncertain="submitUncertain"
      :editing-disabled="checkoutEditingDisabled"
      @back="backToSessions"
      @toggle="toggleSeat"
      @reserve="submitReservation"
      @refresh="refreshSeats"
      @clear="clearSelectedSeats"
      @continue-checkout="continueCheckout"
      @abandon-checkout="abandonRecoverable"
      @start-new-checkout="startNewCheckout"
      @retry-confirm="retryOriginalConfirmation"
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
