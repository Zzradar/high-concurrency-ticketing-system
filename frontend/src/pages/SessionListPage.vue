<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import SessionListView from '../views/SessionListView.vue'
import type { TicketEvent, TicketSession } from '../types'

const route = useRoute()
const router = useRouter()
const event = ref<TicketEvent | null>(null)
const sessions = ref<TicketSession[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const eventId = String(route.params.eventId)
    ;[event.value, sessions.value] = await Promise.all([
      ticketApi.getEvent(eventId),
      ticketApi.getSessions(eventId),
    ])
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '场次加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</div>
  <SessionListView v-if="event" :event="event" :sessions="sessions" :loading="loading" @back="router.push('/events')" @select="router.push(`/sessions/${$event.id}/seats`)" />
</template>
