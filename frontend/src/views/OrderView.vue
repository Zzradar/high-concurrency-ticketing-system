<script setup lang="ts">
import { ArrowLeft, CreditCard, Hourglass, RotateCcw, X } from '@lucide/vue'
import OrderSummary from '../components/OrderSummary.vue'
import { isMockMode } from '../api/ticketApi'
import type { PaymentAttempt, Seat, TicketEvent, TicketOrder, TicketSession } from '../types'
import { formatCny } from '../utils/money'

defineProps<{
  order: TicketOrder
  event: TicketEvent
  session: TicketSession
  seats: Seat[]
  refreshing: boolean
  paymentStarting: boolean
  paymentPolling: boolean
  cancelling: boolean
  paymentAttempt: PaymentAttempt | null
}>()

defineEmits<{
  pay: []
  cancel: []
  expire: []
  refresh: []
  startOver: []
}>()
</script>

<template>
  <main class="page-shell">
    <button class="back-button" type="button" @click="$emit('startOver')">
      <ArrowLeft :size="17" aria-hidden="true" />
      返回活动列表
    </button>

    <section class="order-page-heading">
      <div>
        <p class="eyebrow">YOUR ORDER</p>
        <h1>{{ order.status === 'PENDING_PAYMENT' ? '请确认并完成支付' : '订单详情' }}</h1>
      </div>
      <button class="secondary-button secondary-button--small" type="button" :disabled="refreshing" @click="$emit('refresh')">
        <RotateCcw :size="16" aria-hidden="true" />
        刷新状态
      </button>
    </section>

    <OrderSummary
      :order="order"
      :event="event"
      :session="session"
      :seats="seats"
      @expiry-reached="$emit('refresh')"
    />

    <section v-if="order.status === 'PENDING_PAYMENT'" class="order-actions">
      <button class="primary-button order-pay-button" type="button" :disabled="paymentStarting || paymentPolling" @click="$emit('pay')">
        <span v-if="paymentStarting || paymentPolling" class="button-spinner"></span>
        <CreditCard v-else :size="19" aria-hidden="true" />
        {{ paymentStarting ? '正在发起支付…' : paymentPolling ? '支付处理中…' : '模拟支付 ' + formatCny(order.totalAmount) }}
      </button>
      <button class="secondary-button" type="button" :disabled="cancelling" @click="$emit('cancel')">
        <span v-if="cancelling" class="button-spinner"></span>
        <X v-else :size="18" aria-hidden="true" />
        {{ cancelling ? '正在取消…' : '取消订单' }}
      </button>
    </section>

    <p v-if="paymentAttempt?.status === 'PROCESSING'" class="payment-state" role="status">
      支付渠道处理中；你仍可主动取消订单，迟到成功将自动退款。
    </p>

    <button
      v-if="order.status !== 'PENDING_PAYMENT'"
      class="primary-button order-finish-button"
      type="button"
      @click="$emit('startOver')"
    >
      <RotateCcw :size="18" aria-hidden="true" />
      继续浏览活动
    </button>

    <section v-if="isMockMode && order.status === 'PENDING_PAYMENT'" class="demo-control">
      <div>
        <Hourglass :size="18" aria-hidden="true" />
        <span><strong>演示工具</strong>无需等待 15 分钟，模拟服务端处理超时订单。</span>
      </div>
      <button type="button" :disabled="refreshing" @click="$emit('expire')">模拟订单超时</button>
    </section>
  </main>
</template>
