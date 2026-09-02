<script setup lang="ts">
import { Clock3, RotateCcw, Trash2 } from '@lucide/vue'
import type { CheckoutSession, Seat } from '../types'

const props = defineProps<{
  sessions: CheckoutSession[]
  seats: Seat[]
}>()

defineEmits<{
  continue: [checkout: CheckoutSession]
  abandon: [checkout: CheckoutSession]
  startNew: []
}>()

function seatLabels(checkout: CheckoutSession) {
  const labels = new Map(props.seats.map((seat) => [seat.id, seat.label]))
  return checkout.seatIds.map((id) => labels.get(id) ?? id).join('、') || '尚未选座'
}

function shortId(id: string) {
  return id.length > 18 ? id.slice(0, 18) + '…' : id
}
</script>

<template>
  <section class="recoverable-panel" aria-labelledby="recoverable-title">
    <div class="recoverable-panel__heading">
      <div>
        <p class="eyebrow">RECOVER CHECKOUT</p>
        <h2 id="recoverable-title">发现可继续的购票会话</h2>
      </div>
      <button class="text-button" type="button" @click="$emit('startNew')">开始新的选座</button>
    </div>
    <p>请选择要继续的会话；旧会话不会因开始新选座而自动放弃。</p>
    <div class="recoverable-list">
      <article v-for="checkout in sessions" :key="checkout.id" class="recoverable-item">
        <div>
          <strong>{{ shortId(checkout.id) }}</strong>
          <span><Clock3 :size="14" aria-hidden="true" />{{ checkout.status }}</span>
          <small>{{ checkout.seatIds.length }} 张 · {{ seatLabels(checkout) }}</small>
          <small>更新于 {{ new Date(checkout.updatedAt).toLocaleString('zh-CN') }}</small>
        </div>
        <div class="recoverable-item__actions">
          <button class="secondary-button" type="button" @click="$emit('continue', checkout)">
            <RotateCcw :size="15" aria-hidden="true" />
            {{ checkout.status === 'SUBMITTING' ? '继续处理' : '继续' }}
          </button>
          <button
            v-if="checkout.status === 'SELECTING'"
            class="text-button"
            type="button"
            @click="$emit('abandon', checkout)"
          >
            <Trash2 :size="14" aria-hidden="true" />放弃
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
