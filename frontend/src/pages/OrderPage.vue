<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import { requestNotificationRefresh, showNotice } from '../uiSignals'
import OrderView from '../views/OrderView.vue'
import type { PaymentAttempt, Seat, TicketEvent, TicketOrder, TicketSession } from '../types'

const route = useRoute()
const router = useRouter()
const order = ref<TicketOrder | null>(null)
const event = ref<TicketEvent | null>(null)
const session = ref<TicketSession | null>(null)
const seats = ref<Seat[]>([])
const paymentAttempt = ref<PaymentAttempt | null>(null)
const loading = ref(true)
const paymentStarting = ref(false)
const paymentPolling = ref(false)
const cancelling = ref(false)
const error = ref('')
let paymentGeneration = 0

async function refreshOrder(silent = false) {
  if (!silent) loading.value = true
  try {
    const value = await ticketApi.getOrder(String(route.params.orderId))
    order.value = value
    if (!session.value || session.value.id !== value.sessionId) {
      session.value = await ticketApi.getSession(value.sessionId)
      event.value = await ticketApi.getEvent(value.eventId)
      seats.value = await ticketApi.getSeats(value.sessionId)
    }
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '订单加载失败。'
  } finally {
    loading.value = false
  }
}

function pollPayment(attemptId: string) {
  const generation = ++paymentGeneration
  paymentPolling.value = true
  const started = Date.now()
  const poll = async () => {
    if (generation !== paymentGeneration) return
    try {
      const attempt = await ticketApi.getPaymentAttempt(attemptId)
      paymentAttempt.value = attempt
      await refreshOrder(true)
      if (attempt.status !== 'PROCESSING') {
        paymentPolling.value = false
        requestNotificationRefresh()
        showNotice(attempt.status === 'SUCCEEDED' ? '支付结果已处理，订单状态已同步。' : '支付未完成，请查看最新订单状态。')
        return
      }
    } catch { /* retry transient reads */ }
    if (Date.now() - started >= 15000) {
      paymentPolling.value = false
      error.value = '支付结果仍在处理中，请稍后刷新订单和通知。'
      return
    }
    window.setTimeout(poll, 1000)
  }
  void poll()
}

async function pay() {
  if (!order.value) return
  paymentStarting.value = true
  error.value = ''
  try {
    const result = await ticketApi.payOrder(order.value.id)
    order.value = result.order
    paymentAttempt.value = result.paymentAttempt
    const messages = {
      STARTED_NEW: '正在处理支付……',
      REUSED_PROCESSING: '该订单已有支付正在处理中，正在同步同一笔支付结果。',
      ALREADY_PAID: '该订单此前已经完成支付，已同步最新订单状态。',
    }
    showNotice(messages[result.disposition])
    if (result.paymentAttempt?.status === 'PROCESSING') pollPayment(result.paymentAttempt.id)
    requestNotificationRefresh()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '支付请求结果未知，已重新读取订单。'
    await refreshOrder(true)
  } finally {
    paymentStarting.value = false
  }
}

async function cancel() {
  if (!order.value) return
  cancelling.value = true
  error.value = ''
  try {
    const result = await ticketApi.cancelOrder(order.value.id)
    order.value = result.order
    showNotice(result.disposition === 'CANCELLED_NOW'
      ? '订单已取消，座位已释放。'
      : '该订单此前已经取消，已同步最新状态。')
    requestNotificationRefresh()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '取消订单失败。'
    await refreshOrder(true)
  } finally {
    cancelling.value = false
  }
}

async function expire() {
  if (!order.value) return
  order.value = await ticketApi.expireOrderForDemo(order.value.id)
}

function focusSync() {
  void refreshOrder(true)
  requestNotificationRefresh()
}

onMounted(() => {
  void refreshOrder()
  window.addEventListener('focus', focusSync)
})
onBeforeUnmount(() => {
  paymentGeneration += 1
  window.removeEventListener('focus', focusSync)
})
</script>

<template>
  <p v-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</p>
  <p v-if="loading && !order" class="page-shell">正在加载订单…</p>
  <OrderView v-else-if="order && event && session" :order="order" :event="event" :session="session" :seats="seats" :refreshing="loading" :payment-starting="paymentStarting" :payment-polling="paymentPolling" :cancelling="cancelling" :payment-attempt="paymentAttempt" @pay="pay" @cancel="cancel" @expire="expire" @refresh="refreshOrder" @start-over="router.push('/events')" />
</template>
