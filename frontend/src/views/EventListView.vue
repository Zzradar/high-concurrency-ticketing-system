<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import EventCard from '../components/EventCard.vue'
import type { TicketEvent } from '../types'

defineProps<{
  events: TicketEvent[]
  loading: boolean
}>()

defineEmits<{ select: [event: TicketEvent] }>()
</script>

<template>
  <main class="page-shell">
    <section class="page-intro">
      <div>
        <p class="eyebrow">CURATED EVENTS · SHANGHAI</p>
        <h1>这一场，值得亲临。</h1>
        <p>从演出到决赛，选择你期待的现场。座位库存将在提交时由服务端最终确认。</p>
      </div>
      <div class="intro-note">
        <Sparkles :size="19" aria-hidden="true" />
        <span><strong>本周精选</strong>2 场活动正在售票</span>
      </div>
    </section>

    <section aria-labelledby="event-list-title">
      <div class="section-heading">
        <h2 id="event-list-title">正在售票</h2>
        <span>{{ events.length }} 场活动</span>
      </div>
      <div v-if="loading" class="event-list" aria-label="正在加载活动">
        <div v-for="index in 2" :key="index" class="event-card skeleton-card"></div>
      </div>
      <div v-else class="event-list">
        <EventCard v-for="event in events" :key="event.id" :event="event" @select="$emit('select', $event)" />
      </div>
    </section>
  </main>
</template>
