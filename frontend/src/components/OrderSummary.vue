<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, Clock3, ShieldCheck, XCircle } from '@lucide/vue'
import type { OrderStatus, Seat, TicketEvent, TicketOrder, TicketSession } from '../types'

const props = defineProps<{
  order: TicketOrder
  event: TicketEvent
  session: TicketSession
  seats: Seat[]
}>()

const emit = defineEmits<{ expiryReached: [] }>()
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined

const remainingSeconds = computed(() =>
  Math.max(0, Math.floor((Date.parse(props.order.expiresAt) - now.value) / 1000)),
)
const countdown = computed(() => {
  const minutes = Math.floor(remainingSeconds.value / 60)
  const seconds = remainingSeconds.value % 60
  return String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0')
})
const selectedSeats = computed(() => props.seats.filter((seat) => props.order.seatIds.includes(seat.id)))

const statusMap: Record<OrderStatus, { title: string; description: string; className: string }> = {
  PENDING_PAYMENT: {
    title: '待支付',
    description: '座位已为你锁定，请在倒计时结束前完成支付。',
    className: 'is-pending',
  },
  PAID: {
    title: '支付成功',
    description: '订单已确认，电子票将在出票后发送至你的账户。',
    className: 'is-success',
  },
  CANCELLED: {
    title: '订单已取消',
    description: '本次锁定的座位已经释放，可重新选择其他场次。',
    className: 'is-cancelled',
  },
  EXPIRED: {
    title: '订单已过期',
    description: '支付时间已结束，座位已由系统自动释放。',
    className: 'is-expired',
  },
}

const status = computed(() => statusMap[props.order.status])

onMounted(() => {
  timer = setInterval(() => {
    const previous = remainingSeconds.value
    now.value = Date.now()
    if (previous > 0 && remainingSeconds.value === 0) emit('expiryReached')
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section :class="['order-summary', status.className]">
    <div class="order-summary__status">
      <div class="order-status-icon">
        <Clock3 v-if="order.status === 'PENDING_PAYMENT'" :size="24" aria-hidden="true" />
        <CheckCircle2 v-else-if="order.status === 'PAID'" :size="24" aria-hidden="true" />
        <XCircle v-else :size="24" aria-hidden="true" />
      </div>
      <div>
        <p class="eyebrow">ORDER STATUS</p>
        <h2>{{ status.title }}</h2>
        <p>{{ status.description }}</p>
      </div>
      <div v-if="order.status === 'PENDING_PAYMENT'" class="countdown">
        <span>剩余支付时间</span>
        <strong>{{ countdown }}</strong>
      </div>
    </div>

    <div class="order-ticket">
      <div class="order-ticket__main">
        <div>
          <span class="order-ticket__category">{{ event.category }}</span>
          <h3>{{ event.name }}</h3>
          <p>{{ session.date }} {{ session.weekday }} · {{ session.time }}</p>
          <p>{{ session.venue }}</p>
        </div>
        <div class="order-ticket__seats">
          <span>座位</span>
          <strong>{{ selectedSeats.map((seat) => seat.label).join(' · ') }}</strong>
        </div>
      </div>
      <div class="order-ticket__stub">
        <span>订单号</span>
        <strong>{{ order.id }}</strong>
        <span>预订金额</span>
        <b>¥{{ order.totalAmount.toLocaleString('zh-CN') }}</b>
      </div>
    </div>

    <div class="order-assurance">
      <ShieldCheck :size="18" aria-hidden="true" />
      <span>数据库事务保护</span>
      <small>订单、预订与座位状态同步更新</small>
    </div>
  </section>
</template>

