<script setup lang="ts">
import { ArrowRight, Clock3, DoorOpen, MapPin } from '@lucide/vue'
import type { TicketSession } from '../types'
import { formatCny } from '../utils/money'

defineProps<{ session: TicketSession }>()
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
      余票{{ session.availability }}
    </div>
    <div class="session-card__action">
      <span>{{ formatCny(session.priceFrom) }} 起</span>
      <button
        class="primary-button primary-button--small"
        type="button"
        :disabled="session.status === 'SOLD_OUT'"
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
