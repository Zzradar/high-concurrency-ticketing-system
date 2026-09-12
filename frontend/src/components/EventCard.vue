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
        <p class="eyebrow">{{ event.city }} · {{ event.status === 'ON_SALE' ? '在售活动' : '即将推出' }}</p>
        <h2>{{ event.name }}</h2>
        <p>{{ event.salesWindow.state === 'OPEN' ? '售票中' : event.salesWindow.state === 'NOT_STARTED' ? '尚未开售' : '售票已结束' }}</p>
        <small>开售 {{ event.salesWindow.startsAt }} · 截止 {{ event.salesWindow.endsAt }}</small>
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
        <button class="text-button" type="button" :aria-label="'查看场次 ' + event.name" @click="$emit('select', event)">
          查看场次
          <ArrowRight :size="17" aria-hidden="true" />
        </button>
      </div>
    </div>
  </article>
</template>
