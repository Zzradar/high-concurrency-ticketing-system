<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import StripePaymentPanel from '../components/StripePaymentPanel.vue'
import BuyerRefundPanel from '../components/BuyerRefundPanel.vue'
import { cleanPaymentQuery } from '../payments/paymentReturn'
import { routeNames } from '../navigation'
import { requestNotificationRefresh, showNotice } from '../uiSignals'
import OrderView from '../views/OrderView.vue'
import type { PaymentAction, PaymentAttempt, Seat, TicketEvent, TicketOrder, TicketSession } from '../types'

const route = useRoute()
const router = useRouter()
const order = ref<TicketOrder | null>(null)
const event = ref<TicketEvent | null>(null)
const session = ref<TicketSession | null>(null)
const seats = ref<Seat[]>([])
const paymentAttempt = ref<PaymentAttempt | null>(null)
const paymentAction = ref<PaymentAction | null>(null)
const paymentBlocked = ref(false)
const stripeMode = ref(Boolean(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY?.trim()))
const loading = ref(true)
const paymentStarting = ref(false)
const paymentPolling = ref(false)
const cancelling = ref(false)
const error = ref('')
const refundSubmitting = ref(false)
const refundMessage = ref('')
let refundTimer: number | undefined
let foreground = document.visibilityState !== 'hidden' && document.hasFocus()
let resumedByVisibility = false
let disposed = false
let orderRead: { page: number; read: number; promise: Promise<boolean> } | null = null
let focusRead: Promise<void> | null = null
let paymentGeneration = 0
let pageGeneration = 0
let readGeneration = 0
let attemptReadGeneration = 0
let paymentTimer: number | undefined

function stopPayment() {
  paymentGeneration++
  attemptReadGeneration++
  window.clearTimeout(paymentTimer)
  paymentPolling.value = false
  paymentAttempt.value = null
  paymentAction.value = null
  paymentBlocked.value = false
  error.value = ''
}

function adoptOrder(value: TicketOrder) {
  order.value = value
  if (value.status !== 'PENDING_PAYMENT') stopPayment()
}

async function refreshOrder(silent = false) {
  const page = pageGeneration
  // Coalesce current reads; invalidated reads must finish before the next GET starts.
  if (orderRead) {
    const pending = orderRead
    if (pending.page === page && pending.read === readGeneration) return pending.promise
    await pending.promise
    if (disposed || page !== pageGeneration) return false
    return refreshOrder(silent)
  }
  if (disposed) return false
  const read = ++readGeneration
  const promise = readOrder(page, read, silent)
  orderRead = { page, read, promise }
  try { return await promise } finally {
    if (orderRead?.promise === promise) orderRead = null
    if (page === pageGeneration && !disposed) scheduleRefund()
  }
}

async function readOrder(page: number, read: number, silent: boolean) {
  window.clearTimeout(refundTimer)
  if (!silent) loading.value = true
  if (!silent) error.value = ''
  try {
    const orderId = String(route.params.orderId)
    let value = await ticketApi.getOrder(orderId)
    if (page !== pageGeneration || read !== readGeneration) return false
    const completed = order.value?.buyerRefund?.status === 'PROCESSING' && value.buyerRefund?.status === 'SUCCEEDED'
    adoptOrder(value)
    refundMessage.value = ''
    if (completed) {
      requestNotificationRefresh()
      value = await ticketApi.getOrder(orderId)
      if (page !== pageGeneration || read !== readGeneration) return false
      adoptOrder(value)
    }
    if (!session.value || session.value.id !== value.sessionId) {
      const details = await Promise.all([ticketApi.getSession(value.sessionId), ticketApi.getEvent(value.eventId), ticketApi.getSeats(value.sessionId)])
      if (page !== pageGeneration || read !== readGeneration) return false
      ;[session.value, event.value, seats.value] = details
    }
    return true
  } catch (cause) {
    if (page !== pageGeneration || read !== readGeneration) return false
    if (cause instanceof TicketApiError && cause.code === 'ORDER_NOT_FOUND') order.value = null
    error.value = '订单加载失败，请稍后刷新。'
    return false
  } finally {
    if (page === pageGeneration && read === readGeneration) loading.value = false
  }
}

function scheduleRefund() {
  window.clearTimeout(refundTimer)
  if (disposed || !foreground || orderRead || refundSubmitting.value || order.value?.buyerRefund?.source !== 'BUYER' || order.value.buyerRefund.status !== 'PROCESSING') return
  refundTimer = window.setTimeout(() => void refreshOrder(true), 2000)
}

async function requestRefund() {
  const current = order.value
  if (!current || refundSubmitting.value || current.buyerRefund || current.refundEligibility?.eligible !== true || Date.parse(current.refundEligibility.deadline) <= Date.now()) return
  const page = pageGeneration
  const read = ++readGeneration
  refundSubmitting.value = true
  refundMessage.value = ''
  window.clearTimeout(refundTimer)
  try {
    const result = await ticketApi.createRefund(current.id)
    if (page !== pageGeneration) return
    const refund = result.refund
    if (refund.source !== 'BUYER' || refund.reason !== 'BUYER_REQUESTED' || refund.orderId !== current.id) {
      throw new Error('Refund identity mismatch')
    }
    if (read === readGeneration && order.value) {
      const { id, orderId, status, amount, currency } = refund
      order.value = { ...order.value, buyerRefund: { id, orderId, status, amount, currency, source: 'BUYER', reason: 'BUYER_REQUESTED' } }
    }
    // A newer read outranks a late POST; success also requires authoritative Order sync.
    if (refund.status === 'SUCCEEDED' || read !== readGeneration || orderRead) {
      readGeneration++
      await refreshOrder(true)
    }
    if (page === pageGeneration) requestNotificationRefresh()
  } catch (cause) {
    if (page !== pageGeneration) return
    if (cause instanceof TicketApiError && cause.code === 'ORDER_NOT_FOUND') {
      order.value = null
      error.value = '订单不存在或不可访问。'
      return
    }
    readGeneration++
    await refreshOrder(true)
    if (page !== pageGeneration) return
    if (cause instanceof TicketApiError && ['ORDER_NOT_REFUNDABLE', 'REFUND_WINDOW_CLOSED'].includes(cause.code)) {
      refundMessage.value = cause.code === 'REFUND_WINDOW_CLOSED' ? '场次已经开始，当前不可退款。' : '订单当前不可退款。'
    } else if (!order.value?.buyerRefund) {
      refundMessage.value = '申请结果暂时无法确认，请刷新或稍后重试。'
    }
  } finally {
    if (page === pageGeneration) {
      refundSubmitting.value = false
      scheduleRefund()
    }
  }
}

async function syncAttempt(attemptId: string, generation: number) {
  const read = ++attemptReadGeneration
  const attempt = await ticketApi.getPaymentAttempt(attemptId)
  if (generation !== paymentGeneration || read !== attemptReadGeneration) return
  if (attempt.id !== attemptId || attempt.orderId !== order.value?.id) {
    error.value = '支付恢复信息与当前订单不匹配，已忽略。'
    return
  }
  paymentAttempt.value = attempt
  if (attempt.status === 'FAILED' || attempt.status === 'SUCCEEDED' || (attempt.status === 'TIMED_OUT' && !paymentAction.value)) {
    stopPayment()
    // Do not reopen payment until the authoritative Order has also been refreshed.
    paymentBlocked.value = true
    const settledGeneration = paymentGeneration
    const refreshed = await refreshOrder(true)
    if (settledGeneration === paymentGeneration && refreshed) paymentBlocked.value = false
    requestNotificationRefresh()
    showNotice(attempt.status === 'SUCCEEDED' ? '支付结果已处理，订单状态已同步。' : '支付未完成，请查看最新订单状态。')
  }
  return attempt.status
}

async function refreshStatus(silent = false) {
  if (!silent) readGeneration++
  const generation = paymentGeneration
  const attemptId = paymentAttempt.value?.id
  const refreshed = await refreshOrder(silent)
  if (!refreshed || generation !== paymentGeneration) return
  if (!paymentAction.value && paymentAttempt.value?.status !== 'PROCESSING') {
    paymentBlocked.value = false
    return
  }
  if (!attemptId) return
  try {
    await syncAttempt(attemptId, generation)
  } catch {
    if (generation === paymentGeneration) error.value = '支付结果暂未确认，请稍后刷新订单状态。'
  }
}

function pollPayment(attemptId: string) {
  window.clearTimeout(paymentTimer)
  const generation = ++paymentGeneration
  paymentPolling.value = true
  const started = Date.now()
  const poll = async () => {
    if (generation !== paymentGeneration) return
    try {
      await syncAttempt(attemptId, generation)
      if (generation !== paymentGeneration) return
      await refreshOrder(true)
      if (generation !== paymentGeneration) { requestNotificationRefresh(); return }
    } catch { /* retry transient reads */ }
    if (generation !== paymentGeneration) return
    if (Date.now() - started >= 15000) {
      paymentPolling.value = false
      error.value = '支付结果仍在处理中，请稍后刷新订单和通知。'
      return
    }
    paymentTimer = window.setTimeout(poll, 1000)
  }
  void poll()
}

async function pay() {
  if (!order.value || order.value.status !== 'PENDING_PAYMENT' || paymentStarting.value || paymentPolling.value || cancelling.value || paymentBlocked.value || paymentAction.value) return
  const page = pageGeneration
  stopPayment()
  const generation = paymentGeneration
  paymentStarting.value = true
  error.value = ''
  try {
    const result = await ticketApi.payOrder(order.value.id)
    if (page !== pageGeneration || generation !== paymentGeneration) return
    readGeneration++
    adoptOrder(result.order)
    paymentAttempt.value = result.order.status === 'PENDING_PAYMENT' ? result.paymentAttempt : null
    if (result.paymentAttempt?.provider === 'stripe' || result.paymentAction) stripeMode.value = true
    const messages = {
      STARTED_NEW: '正在处理支付……',
      REUSED_PROCESSING: '该订单已有支付正在处理中，正在同步同一笔支付结果。',
      ALREADY_PAID: '该订单此前已经完成支付，已同步最新订单状态。',
    }
    showNotice(messages[result.disposition])
    if (result.order.status === 'PENDING_PAYMENT' && result.disposition !== 'ALREADY_PAID') {
      if (result.paymentAction != null) {
        const action = result.paymentAction
        if (action.provider !== 'stripe' || action.type !== 'CLIENT_CONFIRM') {
          error.value = '当前支付方式暂不受此客户端支持；请刷新订单状态。'
          paymentBlocked.value = true
        } else if (typeof action.clientSecret !== 'string' || !action.clientSecret.trim() || !result.paymentAttempt || result.paymentAttempt.orderId !== result.order.id) {
          error.value = '支付组件数据无效，请刷新订单状态。'
          paymentBlocked.value = true
        } else if (result.paymentAttempt.status === 'PROCESSING') {
          paymentAction.value = action
        }
      } else if (result.paymentAttempt?.status === 'PROCESSING') pollPayment(result.paymentAttempt.id)
    }
    requestNotificationRefresh()
  } catch (cause) {
    if (page !== pageGeneration || generation !== paymentGeneration) return
    error.value = cause instanceof TicketApiError ? cause.message : '支付请求结果未知，已重新读取订单。'
    await refreshOrder(true)
  } finally {
    if (page === pageGeneration) paymentStarting.value = false
  }
}

function submitted(attemptId: string, outcome: 'submitted' | 'card_error' | 'unknown') {
  if (order.value?.status !== 'PENDING_PAYMENT' || paymentAttempt.value?.id !== attemptId) return
  error.value = outcome === 'unknown' ? '支付结果暂未确认，正在同步服务器状态。' : ''
  pollPayment(attemptId)
  void refreshOrder(true)
}

async function cancel() {
  if (!order.value || cancelling.value) return
  const page = pageGeneration
  cancelling.value = true
  error.value = ''
  try {
    const result = await ticketApi.cancelOrder(order.value.id)
    if (page !== pageGeneration) return
    readGeneration++
    adoptOrder(result.order)
    stopPayment()
    showNotice(result.disposition === 'CANCELLED_NOW'
      ? '订单已取消，座位已释放。'
      : '该订单此前已经取消，已同步最新状态。')
    requestNotificationRefresh()
    await refreshOrder(true)
  } catch (cause) {
    if (page !== pageGeneration) return
    error.value = cause instanceof TicketApiError ? cause.message : '取消订单失败。'
    await refreshOrder(true)
  } finally {
    if (page === pageGeneration) cancelling.value = false
  }
}

async function expire() {
  if (!order.value) return
  const page = pageGeneration
  const value = await ticketApi.expireOrderForDemo(order.value.id)
  if (page === pageGeneration) adoptOrder(value)
}

function syncForeground() {
  foreground = document.visibilityState !== 'hidden'
  if (!foreground || focusRead || disposed) return
  focusRead = refreshStatus(true).finally(() => { focusRead = null })
  requestNotificationRefresh()
}

function focusSync() {
  // One activation can emit both events, even with a completed GET between them.
  if (resumedByVisibility) { resumedByVisibility = false; return }
  syncForeground()
}

function blurSync() {
  foreground = false
  resumedByVisibility = false
  window.clearTimeout(refundTimer)
}

function visibilitySync() {
  if (document.visibilityState === 'hidden') blurSync()
  else if (!foreground && document.hasFocus()) {
    syncForeground()
    resumedByVisibility = true
  }
}

async function restore() {
  const page = pageGeneration
  const returning = route.query.paymentReturn === '1'
  const hint = route.query.paymentAttemptId
  const query = cleanPaymentQuery(route.query)
  const hasPaymentQuery = Object.keys(query).length !== Object.keys(route.query).length
  try {
    const accessible = await refreshOrder()
    if (!returning || !accessible || !order.value || page !== pageGeneration) return
    if (typeof hint !== 'string' || !hint.trim()) {
      error.value = '支付恢复信息无效，请刷新订单状态。'
      return
    }
    const attempt = await ticketApi.getPaymentAttempt(hint)
    if (page !== pageGeneration) return
    if (attempt.orderId !== order.value.id) {
      error.value = '支付恢复信息与当前订单不匹配，已忽略。'
      return
    }
    paymentAttempt.value = attempt
    if (attempt.provider === 'stripe') stripeMode.value = true
    if (attempt.status === 'PROCESSING' && order.value.status === 'PENDING_PAYMENT') pollPayment(attempt.id)
    else { await refreshOrder(true); requestNotificationRefresh() }
  } catch {
    if (page === pageGeneration) error.value = '无法恢复该支付尝试，请刷新订单状态。'
  } finally {
    if (page === pageGeneration && hasPaymentQuery) await router.replace({ path: route.path, query, hash: route.hash })
  }
}

watch(() => route.params.orderId, () => {
  pageGeneration++
  readGeneration++
  window.clearTimeout(refundTimer)
  refundSubmitting.value = false
  refundMessage.value = ''
  stopPayment()
  order.value = null
  session.value = null
  event.value = null
  paymentAttempt.value = null
  paymentStarting.value = false
  cancelling.value = false
  stripeMode.value = Boolean(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY?.trim())
  void restore()
})

onMounted(() => {
  void restore()
  window.addEventListener('focus', focusSync)
  window.addEventListener('blur', blurSync)
  document.addEventListener('visibilitychange', visibilitySync)
})
onBeforeUnmount(() => {
  pageGeneration++
  readGeneration++
  disposed = true
  window.clearTimeout(refundTimer)
  stopPayment()
  window.removeEventListener('focus', focusSync)
  window.removeEventListener('blur', blurSync)
  document.removeEventListener('visibilitychange', visibilitySync)
})
</script>

<template>
  <main v-if="!loading && error && !order" class="page-shell">
    <PageBreadcrumbs
      :items="[
        { label: '我的订单', to: { name: routeNames.orders } },
        { label: String(route.params.orderId) },
      ]"
    />
    <PageState eyebrow="ORDER" title="订单不存在或不可访问" :description="error" action-label="重新加载" @action="refreshStatus" />
  </main>
  <p v-else-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</p>
  <p v-if="loading && !order" class="page-shell">正在加载订单…</p>
  <OrderView v-else-if="order && event && session" :order="order" :event="event" :session="session" :seats="seats" :refreshing="loading" :payment-starting="paymentStarting" :payment-polling="paymentPolling" :cancelling="cancelling" :payment-attempt="paymentAttempt" :stripe-mode="stripeMode" :payment-prepared="Boolean(paymentAction) || paymentBlocked" @pay="pay" @cancel="cancel" @expire="expire" @refresh="refreshStatus" @back-to-orders="router.push({ name: routeNames.orders })" @browse-events="router.push({ name: routeNames.events })">
    <template #refund>
      <BuyerRefundPanel :order="order" :submitting="refundSubmitting" :message="refundMessage" @request="requestRefund" />
    </template>
    <StripePaymentPanel v-if="order.status === 'PENDING_PAYMENT' && paymentAction && paymentAttempt" :client-secret="paymentAction.clientSecret" :payment-attempt-id="paymentAttempt.id" :order-id="order.id" :disabled="cancelling" @submitted="submitted" />
  </OrderView>
</template>
