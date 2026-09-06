<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import EventListView from '../views/EventListView.vue'
import type { TicketEvent } from '../types'
import { routeNames } from '../navigation'

const router = useRouter()
const events = ref<TicketEvent[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    events.value = await ticketApi.getEvents()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '活动加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <main v-if="error" class="page-shell">
    <PageBreadcrumbs :items="[{ label: '活动' }]" />
    <PageState eyebrow="EVENTS" title="活动加载失败" :description="error" action-label="重新加载" @action="load" />
  </main>
  <EventListView
    v-else
    :events="events"
    :loading="loading"
    @select="router.push({ name: routeNames.eventSessions, params: { eventId: $event.id } })"
    @refresh="load"
  />
</template>
