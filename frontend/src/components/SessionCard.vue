<script setup lang="ts">
import { ArrowRight, Clock3, DoorOpen, MapPin } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { ticketApi } from '../api/ticketApi'
import { useSalesWindow } from '../utils/salesWindow'
import type { TicketSession } from '../types'
import { formatCny } from '../utils/money'

const props = defineProps<{ session: TicketSession; eventAvailable?: boolean }>()
const current = ref(props.session)
watch(() => props.session, value => { current.value = value })
const { label } = useSalesWindow(computed(() => current.value.salesWindow), async () => {
  const id = current.value.id
  const fresh = await ticketApi.getSession(id)
  if (current.value.id === id) current.value = fresh
})
defineEmits<{ select: [session: TicketSession] }>()
</script>

<template>
  <article class="session-card">
    <div class="session-card__date">
      <strong>{{ session.date }}</strong>
      <span>{{ session.weekday }}</span>
    </div>
    <div class="session-card__time">
      <span class="eyebrow">开演时间</span>
      <strong>{{ session.time }}</strong>
    </div>
    <div class="session-card__details">
      <span><MapPin :size="17" aria-hidden="true" />{{ session.venue }}</span>
      <span><DoorOpen :size="17" aria-hidden="true" />{{ session.gateTime }} 开始入场</span>
    </div>
    <div class="session-card__availability">
      <span :class="['availability-dot', 'is-' + session.availability]"></span>
      余票{{ session.availability }} · {{ label }}
      <small>开售 {{ current.salesWindow.startsAt }} · 截止 {{ current.salesWindow.endsAt }}</small>
    </div>
    <div class="session-card__action">
      <span>{{ formatCny(session.priceFrom) }} 起</span>
      <button
        class="primary-button primary-button--small"
        type="button"
        :aria-label="'进入选座 ' + session.date + ' ' + session.time"
        :disabled="eventAvailable === false || current.status !== 'ON_SALE' || current.salesWindow.state !== 'OPEN'"
        @click="$emit('select', session)"
      >
        <Clock3 v-if="session.status === 'SOLD_OUT'" :size="16" aria-hidden="true" />
        <template v-else>
          进入选座
          <ArrowRight :size="16" aria-hidden="true" />
        </template>
      </button>
    </div>
  </article>
</template>
