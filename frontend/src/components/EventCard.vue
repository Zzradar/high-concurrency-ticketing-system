<script setup lang="ts">
import { ArrowRight, CalendarDays, MapPin } from '@lucide/vue'
import type { TicketEvent } from '../types'

defineProps<{ event: TicketEvent }>()
defineEmits<{ select: [event: TicketEvent] }>()
</script>

<template>
  <article class="event-card">
    <div class="event-card__visual">
      <img :src="event.cover" :alt="event.name + '活动现场氛围图'" />
      <span class="event-card__category">{{ event.category }}</span>
    </div>
    <div class="event-card__body">
      <div>
        <p class="eyebrow">{{ event.city }} · 正在售票</p>
        <h2>{{ event.name }}</h2>
        <p class="event-card__description">{{ event.description }}</p>
      </div>
      <dl class="event-card__meta">
        <div>
          <CalendarDays :size="18" aria-hidden="true" />
          <span>{{ event.dateRange }}</span>
        </div>
        <div>
          <MapPin :size="18" aria-hidden="true" />
          <span>{{ event.venue }}</span>
        </div>
      </dl>
      <div class="event-card__footer">
        <span>{{ event.sessionCount }} 个可选场次</span>
        <button class="text-button" type="button" @click="$emit('select', event)">
          查看场次
          <ArrowRight :size="17" aria-hidden="true" />
        </button>
      </div>
    </div>
  </article>
</template>
