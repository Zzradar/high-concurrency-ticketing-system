<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import EventListView from '../views/EventListView.vue'
import type { TicketEvent } from '../types'

const router = useRouter()
const events = ref<TicketEvent[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    events.value = await ticketApi.getEvents()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '活动加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</div>
  <EventListView :events="events" :loading="loading" @select="router.push(`/events/${$event.id}/sessions`)" />
</template>
