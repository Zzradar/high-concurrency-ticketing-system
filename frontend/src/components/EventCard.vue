<script setup lang="ts">
import { ArrowRight, CalendarDays, MapPin } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { ticketApi } from '../api/ticketApi'
import { isSalesWindow } from '../utils/eventContract'
import { useSalesWindow } from '../utils/salesWindow'
import type { TicketEvent } from '../types'

const props = defineProps<{ event: TicketEvent }>()
const current = ref(props.event)
watch(() => props.event, value => { current.value = value })
const { label } = useSalesWindow(computed(() => current.value.salesWindow), async () => {
  const id = current.value.id
  const fresh = await ticketApi.getEvent(id)
  if (current.value.id === id) current.value = fresh
})
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
        <p>{{ label }}</p>
        <small v-if="isSalesWindow(current.salesWindow)">开售 {{ current.salesWindow.startsAt }} · 截止 {{ current.salesWindow.endsAt }}</small>
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
