<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import EventCard from '../components/EventCard.vue'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import type { TicketEvent } from '../types'

defineProps<{
  events: TicketEvent[]
  loading: boolean
}>()

defineEmits<{
  select: [event: TicketEvent]
  refresh: []
}>()
</script>

<template>
  <main class="page-shell">
    <PageBreadcrumbs :items="[{ label: '活动' }]" />
    <section class="page-intro">
      <div>
        <p class="eyebrow">CURATED EVENTS · TICKET TRACE</p>
        <h1>这一场，值得亲临。</h1>
        <p>从演出到赛事，查看近期活动，选择合适的场次和座位。</p>
      </div>
      <div class="intro-note">
        <Sparkles :size="19" aria-hidden="true" />
        <span><strong>本周精选</strong>{{ loading ? '正在加载活动' : events.length ? `共 ${events.length} 场活动可浏览` : '暂无可浏览活动' }}</span>
      </div>
    </section>

    <section aria-labelledby="event-list-title">
      <div class="section-heading">
        <h2 id="event-list-title">可浏览活动</h2>
        <span>{{ events.length }} 场活动</span>
      </div>
      <div v-if="loading" class="event-list" aria-label="正在加载活动">
        <div v-for="index in 2" :key="index" class="event-card skeleton-card"></div>
      </div>
      <PageState
        v-else-if="!events.length"
        eyebrow="EVENTS"
        title="暂无可浏览活动"
        description="当前没有可浏览的活动，请稍后再来看看。"
        action-label="重新加载"
        @action="$emit('refresh')"
      />
      <div v-else class="event-list">
        <EventCard v-for="event in events" :key="event.id" :event="event" @select="$emit('select', $event)" />
      </div>
    </section>
  </main>
</template>
