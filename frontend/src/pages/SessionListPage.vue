<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import SessionListView from '../views/SessionListView.vue'
import type { TicketEvent, TicketSession } from '../types'
import { routeNames, setPageTitle } from '../navigation'

const route = useRoute()
const router = useRouter()
const event = ref<TicketEvent | null>(null)
const sessions = ref<TicketSession[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const eventId = String(route.params.eventId)
    ;[event.value, sessions.value] = await Promise.all([
      ticketApi.getEvent(eventId),
      ticketApi.getSessions(eventId),
    ])
    setPageTitle(event.value.name + ' · 场次')
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '场次加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <main v-if="error && !event" class="page-shell">
    <PageBreadcrumbs :items="[{ label: '活动', to: { name: routeNames.events } }, { label: '场次' }]" />
    <PageState eyebrow="SESSIONS" title="无法打开该活动" :description="error" action-label="重新加载" @action="load" />
  </main>
  <SessionListView
    v-else-if="event"
    :event="event"
    :sessions="sessions"
    :loading="loading"
    @back="router.push({ name: routeNames.events })"
    @select="router.push({ name: routeNames.sessionSeats, params: { sessionId: $event.id } })"
  />
</template>
