<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authState, checkoutLocatorKey } from '../auth/authState'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import { requestNotificationRefresh, showNotice } from '../uiSignals'
import SeatSelectionView from '../views/SeatSelectionView.vue'
import type { CheckoutSession, Seat, TicketEvent, TicketOrder, TicketSession } from '../types'

const route = useRoute()
const router = useRouter()
const event = ref<TicketEvent | null>(null)
const session = ref<TicketSession | null>(null)
const seats = ref<Seat[]>([])
const selectedSeatIds = ref<string[]>([])
const checkout = ref<CheckoutSession | null>(null)
const recoverable = ref<CheckoutSession[]>([])
const sessionOrders = ref<TicketOrder[]>([])
const loading = ref(true)
const syncing = ref(false)
const confirming = ref(false)
const submittingPolling = ref(false)
const submitUncertain = ref(false)
const error = ref('')
let pollingGeneration = 0

const selectedSeats = computed(() => seats.value.filter((seat) => selectedSeatIds.value.includes(seat.id)))
const editingDisabled = computed(() => syncing.value || confirming.value || submittingPolling.value || checkout.value?.status !== 'SELECTING' && !!checkout.value)
const existingOrder = computed(() => sessionOrders.value.find((order) => order.status === 'PENDING_PAYMENT') ?? sessionOrders.value.find((order) => order.status === 'PAID'))

function locatorWrite(value: CheckoutSession) {
  const key = checkoutLocatorKey()
  if (key) sessionStorage.setItem(key, JSON.stringify({ checkoutSessionId: value.id, sessionId: value.sessionId }))
}

function locatorClear() {
  const key = checkoutLocatorKey()
  if (key) sessionStorage.removeItem(key)
}

async function refreshSeats() {
  if (!session.value) return
  seats.value = await ticketApi.getSeats(session.value.id, checkout.value?.id)
}

async function refreshSessionOrders() {
  if (!session.value || !authState.currentUser.value) {
    sessionOrders.value = []
    return
  }
  sessionOrders.value = await ticketApi.getOrders({ sessionId: session.value.id, limit: 20 })
}

async function activate(value: CheckoutSession) {
  checkout.value = value
  selectedSeatIds.value = [...value.seatIds]
  recoverable.value = []
  locatorWrite(value)
  await refreshSeats()
  if (value.status === 'RESERVED' && value.order) {
    showNotice('该购票会话此前已经确认，已同步现有订单。')
    await router.push(`/orders/${value.order.id}`)
  } else if (value.status === 'SUBMITTING') {
    startSubmittingPoll(value.id)
  }
}

async function recoverCheckout() {
  if (!session.value || !authState.currentUser.value) return
  const key = checkoutLocatorKey()
  if (key) {
    try {
      const locator = JSON.parse(sessionStorage.getItem(key) ?? '{}') as { checkoutSessionId?: string; sessionId?: string }
      if (locator.sessionId === session.value.id && locator.checkoutSessionId) {
        const value = await ticketApi.getCheckoutSession(locator.checkoutSessionId)
        if (value.status !== 'ABANDONED') {
          await activate(value)
          return
        }
      }
    } catch {
      locatorClear()
    }
  }
  recoverable.value = await ticketApi.listRecoverableCheckoutSessions(session.value.id)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const sessionId = String(route.params.sessionId)
    session.value = await ticketApi.getSession(sessionId)
    ;[event.value, seats.value] = await Promise.all([
      ticketApi.getEvent(session.value.eventId),
      ticketApi.getSeats(sessionId),
    ])
    await Promise.all([recoverCheckout(), refreshSessionOrders()])
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '座位图加载失败。'
  } finally {
    loading.value = false
  }
}

async function requireLogin() {
  if (authState.currentUser.value) return true
  await router.push({ path: '/login', query: { redirect: route.fullPath } })
  return false
}

async function toggleSeat(seat: Seat) {
  if (!(await requireLogin()) || editingDisabled.value) return
  let next = selectedSeatIds.value.includes(seat.id)
    ? selectedSeatIds.value.filter((id) => id !== seat.id)
    : [...selectedSeatIds.value, seat.id]
  if (!selectedSeatIds.value.includes(seat.id) && seat.status !== 'AVAILABLE') return
  if (next.length > 6) {
    error.value = '每个订单最多选择 6 个座位。'
    return
  }
  syncing.value = true
  error.value = ''
  try {
    const value = checkout.value
      ? await ticketApi.replaceCheckoutSessionSeats(checkout.value.id, next, checkout.value.revision)
      : next.length && session.value
        ? await ticketApi.createCheckoutSession(session.value.id, next)
        : null
    if (value) {
      checkout.value = value
      selectedSeatIds.value = [...value.seatIds]
      locatorWrite(value)
    }
    await refreshSeats()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '座位选择同步失败。'
    if (checkout.value) {
      try { await activate(await ticketApi.getCheckoutSession(checkout.value.id)) } catch { /* keep visible state */ }
    }
  } finally {
    syncing.value = false
  }
}

async function clearSeats() {
  if (!checkout.value) return
  syncing.value = true
  try {
    checkout.value = await ticketApi.replaceCheckoutSessionSeats(checkout.value.id, [], checkout.value.revision)
    selectedSeatIds.value = []
    locatorWrite(checkout.value)
    await refreshSeats()
  } finally {
    syncing.value = false
  }
}

async function confirmCheckout() {
  if (!(await requireLogin()) || !checkout.value || !selectedSeatIds.value.length) return
  confirming.value = true
  error.value = ''
  try {
    const result = await ticketApi.confirmCheckoutSession(checkout.value.id)
    checkout.value = result.checkoutSession
    locatorWrite(result.checkoutSession)
    const messages = {
      CONFIRMED_NOW: '订单创建成功，请在 15 分钟内支付。',
      REUSED_CONFIRMATION: '该购票会话已有确认正在进行，正在同步同一结果。',
      ALREADY_CONFIRMED: '该购票会话此前已经生成订单，已同步现有订单。',
    }
    showNotice(messages[result.disposition])
    requestNotificationRefresh()
    if (result.checkoutSession.order) await router.push(`/orders/${result.checkoutSession.order.id}`)
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '确认结果暂时未知，正在恢复同一购票会话。'
    startSubmittingPoll(checkout.value.id)
  } finally {
    confirming.value = false
  }
}

function startSubmittingPoll(id: string) {
  const generation = ++pollingGeneration
  submittingPolling.value = true
  submitUncertain.value = false
  const started = Date.now()
  const poll = async () => {
    if (generation !== pollingGeneration) return
    try {
      const value = await ticketApi.getCheckoutSession(id)
      checkout.value = value
      if (value.status === 'RESERVED' && value.order) {
        submittingPolling.value = false
        showNotice('该购票会话此前已经生成订单，已同步现有订单。')
        await router.push(`/orders/${value.order.id}`)
        return
      }
      if (value.status !== 'SUBMITTING') {
        submittingPolling.value = false
        await activate(value)
        return
      }
    } catch { /* unknown result remains recoverable */ }
    if (Date.now() - started >= 15000) {
      submittingPolling.value = false
      submitUncertain.value = true
      return
    }
    window.setTimeout(poll, 2000)
  }
  void poll()
}

async function abandon(value: CheckoutSession) {
  try {
    await ticketApi.abandonCheckoutSession(value.id)
    recoverable.value = recoverable.value.filter((item) => item.id !== value.id)
    locatorClear()
    await refreshSeats()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '放弃购票会话失败。'
  }
}

async function handleFocus() {
  requestNotificationRefresh()
  await refreshSessionOrders()
  if (checkout.value) {
    try { await activate(await ticketApi.getCheckoutSession(checkout.value.id)) } catch { /* best effort */ }
  }
}

onMounted(() => {
  void load()
  window.addEventListener('focus', handleFocus)
})
onBeforeUnmount(() => {
  pollingGeneration += 1
  window.removeEventListener('focus', handleFocus)
})
</script>

<template>
  <p v-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</p>
  <section v-if="existingOrder" class="message-banner" role="status">
    <span>{{ existingOrder.status === 'PENDING_PAYMENT' ? '你有本场次待支付订单' : '你已经购买过本场次' }}</span>
    <button type="button" @click="router.push(`/orders/${existingOrder.id}`)">查看订单</button><span>也可继续购票</span>
  </section>
  <SeatSelectionView
    v-if="event && session"
    :event="event" :session="session" :seats="seats" :selected-seats="selectedSeats"
    :selected-seat-ids="selectedSeatIds" :checkout-session="checkout"
    :recoverable-checkout-sessions="recoverable" :loading="loading"
    :checkout-creating="syncing && !checkout" :checkout-sync-in-flight="syncing"
    :confirming="confirming" :submitting-polling="submittingPolling"
    :submit-uncertain="submitUncertain" :editing-disabled="editingDisabled"
    @back="router.push(`/events/${session.eventId}/sessions`)" @toggle="toggleSeat"
    @reserve="confirmCheckout" @refresh="refreshSeats" @clear="clearSeats"
    @continue-checkout="activate" @abandon-checkout="abandon"
    @start-new-checkout="recoverable = []" @retry-confirm="confirmCheckout"
  />
</template>
