<script setup lang="ts">
import { ArrowLeft, CalendarRange, MapPin } from '@lucide/vue'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import SessionCard from '../components/SessionCard.vue'
import type { TicketEvent, TicketSession } from '../types'
import { routeNames } from '../navigation'

defineProps<{
  event: TicketEvent
  sessions: TicketSession[]
  loading: boolean
}>()

defineEmits<{
  back: []
  select: [session: TicketSession]
}>()
</script>

<template>
  <main class="page-shell">
    <PageBreadcrumbs
      :items="[
        { label: '活动', to: { name: routeNames.events } },
        { label: event.name },
        { label: '场次' },
      ]"
    />
    <button class="back-button" type="button" @click="$emit('back')">
      <ArrowLeft :size="17" aria-hidden="true" />
      返回活动列表
    </button>

    <section class="event-context">
      <img :src="event.cover" :alt="event.name + '活动封面'" />
      <div>
        <p class="eyebrow">{{ event.category }} · {{ event.city }}</p>
        <h1>{{ event.name }}</h1>
        <p>{{ event.description }}</p>
        <div class="event-context__meta">
          <span><CalendarRange :size="17" aria-hidden="true" />{{ event.dateRange }}</span>
          <span><MapPin :size="17" aria-hidden="true" />{{ event.venue }}</span>
        </div>
      </div>
    </section>

    <section aria-labelledby="session-list-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">CHOOSE A SESSION</p>
          <h2 id="session-list-title">选择场次</h2>
        </div>
        <span>{{ sessions.length }} 个场次可选</span>
      </div>
      <div v-if="loading" class="session-list" aria-label="正在加载场次">
        <div v-for="index in 3" :key="index" class="session-card skeleton-card"></div>
      </div>
      <PageState
        v-else-if="!sessions.length"
        eyebrow="SESSIONS"
        title="当前活动暂无可选场次"
        description="该活动暂时没有正在售票的场次，请返回活动列表选择其他活动。"
      />
      <div v-else class="session-list">
        <SessionCard
          v-for="session in sessions"
          :key="session.id"
          :session="session"
          :event-available="event.status === 'ON_SALE'"
          @select="$emit('select', $event)"
        />
      </div>
    </section>
  </main>
</template>
