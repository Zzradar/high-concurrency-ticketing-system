<script setup lang="ts">
import { RefreshCw, ShieldCheck, Ticket, X } from '@lucide/vue'
import { computed } from 'vue'
import type { CheckoutSessionStatus, Seat, TicketSession } from '../types'
import { formatCny } from '../utils/money'

const props = defineProps<{
  selectedSeats: Seat[]
  session: TicketSession
  checkoutStatus?: CheckoutSessionStatus
  checkoutCreating: boolean
  checkoutSyncInFlight: boolean
  confirming: boolean
  submittingPolling: boolean
  submitUncertain: boolean
  editingDisabled: boolean
}>()

defineEmits<{
  reserve: []
  remove: [seat: Seat]
  clear: []
  refresh: []
  retryConfirm: []
}>()

const totalAmount = computed(() =>
  props.selectedSeats.reduce((total, seat) => total + seat.price, 0),
)
</script>

<template>
  <aside class="selection-panel" aria-labelledby="selection-title">
    <div class="selection-panel__header">
      <div>
        <p class="eyebrow">YOUR SELECTION</p>
        <h2 id="selection-title">已选座位</h2>
      </div>
      <button class="icon-button" type="button" aria-label="刷新座位状态" @click="$emit('refresh')">
        <RefreshCw :size="18" aria-hidden="true" />
      </button>
    </div>

    <div v-if="selectedSeats.length" class="selected-list">
      <button
        v-for="seat in selectedSeats"
        :key="seat.id"
        class="selected-seat"
        :class="{ 'selected-seat--unavailable': seat.status !== 'AVAILABLE' }"
        type="button"
        :aria-label="'移除座位 ' + seat.label"
        :disabled="editingDisabled"
        @click="$emit('remove', seat)"
      >
        <span><Ticket :size="16" aria-hidden="true" />{{ seat.label }}</span>
        <small>
          {{ seat.zone }} · {{ formatCny(seat.price) }}
          <em v-if="seat.status !== 'AVAILABLE'">当前不可用</em>
        </small>
        <X :size="15" aria-hidden="true" />
      </button>
    </div>
    <div v-else class="selection-empty">
      <Ticket :size="30" stroke-width="1.4" aria-hidden="true" />
      <strong>还没有选择座位</strong>
      <span>从左侧座位图中选择 1—6 个座位</span>
    </div>

    <div class="selection-meta">
      <div>
        <span>场次</span>
        <strong>{{ session.date }} {{ session.time }}</strong>
      </div>
      <div>
        <span>票数</span>
        <strong>{{ selectedSeats.length }} 张</strong>
      </div>
      <div class="selection-total">
        <span>合计</span>
        <strong>{{ formatCny(totalAmount) }}</strong>
      </div>
    </div>

    <button
      class="primary-button primary-button--full"
      type="button"
      :disabled="
        (!selectedSeats.length && !submitUncertain) ||
        (editingDisabled && !submitUncertain)
      "
      @click="submitUncertain ? $emit('retryConfirm') : $emit('reserve')"
    >
      <span v-if="confirming || submittingPolling || checkoutCreating" class="button-spinner"></span>
      <ShieldCheck v-else :size="18" aria-hidden="true" />
      {{
        submitUncertain
          ? '继续原确认'
          : submittingPolling || checkoutStatus === 'SUBMITTING'
            ? '正在确认预订…'
            : confirming
              ? '正在确认座位…'
              : checkoutCreating
                ? '正在保存选座…'
                : '提交预订'
      }}
    </button>
    <p v-if="submitUncertain" class="selection-panel__warning">
      确认结果暂时无法确定。继续原确认不会创建第二份订单。
    </p>
    <p v-else-if="checkoutSyncInFlight && !confirming" class="selection-panel__sync">
      正在后台同步最新选座…
    </p>
    <p class="selection-panel__hint">
      提交后将由服务端原子锁定全部座位，任一座位不可用则整单失败。
    </p>
  </aside>
</template>
