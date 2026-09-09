<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { TicketOrder } from '../types'
import { formatCny, formatMoney } from '../utils/money'

const props = defineProps<{ order: TicketOrder; submitting: boolean; message: string }>()
const emit = defineEmits<{ request: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const deadlinePassed = ref(false)
let deadlineTimer: number | undefined
const buyerRefund = computed(() => props.order.buyerRefund?.source === 'BUYER' ? props.order.buyerRefund : null)
const eligible = computed(() => !buyerRefund.value && props.order.refundEligibility?.eligible === true && !deadlinePassed.value)
const unavailable = computed(() => {
  if (deadlinePassed.value || props.order.refundEligibility?.reason === 'REFUND_WINDOW_CLOSED') return '场次已经开始，当前不可退款。'
  if (props.order.refundEligibility?.reason === 'ALREADY_REQUESTED') return '该订单已有退款申请，请刷新订单状态。'
  return '订单当前不可退款。'
})
const descriptions = {
  PROCESSING: '退款处理中，完成前订单和座位权益仍然有效。',
  SUCCEEDED: '退款已完成，订单已取消，原座位已释放。',
  FAILED: '退款失败，订单和座位权益仍然有效。当前版本不支持再次自动退款。',
}

function close() { dialog.value?.close() }
function open() {
  if (eligible.value && !props.submitting && !dialog.value?.open) dialog.value?.showModal()
}
function confirm() {
  if (!dialog.value?.open || !eligible.value || props.submitting) return
  // Close synchronously; duplicate confirmation events cannot emit another request.
  close()
  emit('request')
}
function updateDeadline() {
  window.clearTimeout(deadlineTimer)
  const deadline = props.order.refundEligibility?.deadline
  const remaining = deadline ? Date.parse(deadline) - Date.now() : NaN
  deadlinePassed.value = Number.isFinite(remaining) && remaining <= 0
  if (remaining > 0 && !buyerRefund.value) {
    deadlineTimer = window.setTimeout(updateDeadline, Math.min(remaining, 2147483647))
  }
}
watch(() => [props.order.id, props.order.refundEligibility?.deadline, buyerRefund.value?.status], updateDeadline, { immediate: true })
watch(() => props.order.id, close)
watch(eligible, (value) => { if (!value) close() })
onBeforeUnmount(() => { window.clearTimeout(deadlineTimer); close() })
</script>

<template>
  <section class="buyer-refund-panel" aria-label="全额退款">
    <h2>全额退款</h2>
    <template v-if="buyerRefund">
      <p role="status">{{ descriptions[buyerRefund.status] }}</p>
      <p>退款金额：{{ formatMoney(buyerRefund.amount, buyerRefund.currency) }}</p>
      <small>退款编号：{{ buyerRefund.id }}</small>
    </template>
    <template v-else>
      <p v-if="!eligible">{{ unavailable }}</p>
      <button v-if="eligible || submitting" class="secondary-button" type="button" :disabled="submitting || !eligible" @click="open">
        {{ submitting ? '正在提交退款申请…' : '申请全额退款' }}
      </button>
    </template>
    <p v-if="message" class="message-banner message-banner--error" role="alert">{{ message }}</p>
    <dialog ref="dialog" aria-labelledby="refund-confirm-title" aria-describedby="refund-confirm-description">
      <h2 id="refund-confirm-title">确认申请全额退款</h2>
      <p id="refund-confirm-description">整单 {{ formatCny(order.totalAmount) }} 将原路退款。退款处理中，完成前订单和座位权益仍然有效。</p>
      <div class="order-actions">
        <button class="secondary-button" type="button" autofocus @click="close">暂不退款</button>
        <button class="primary-button" type="button" :disabled="submitting || !eligible" @click="confirm">确认退款</button>
      </div>
    </dialog>
  </section>
</template>

<style scoped>
.buyer-refund-panel { margin: 24px 0; padding: 24px; border: 1px solid #e2e8f0; border-radius: 16px; background: white; }
h2 { margin: 0 0 12px; font-size: 20px; }
small { overflow-wrap: anywhere; }
dialog { max-width: min(480px, calc(100vw - 32px)); padding: 24px; border: 1px solid #e2e8f0; border-radius: 16px; }
dialog::backdrop { background: rgb(15 23 42 / 45%); }
</style>
