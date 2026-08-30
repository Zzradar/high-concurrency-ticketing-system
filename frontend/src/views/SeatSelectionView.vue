<script setup lang="ts">
import { ArrowLeft, CalendarDays, MapPin } from '@lucide/vue'
import SeatGrid from '../components/SeatGrid.vue'
import SelectedSeats from '../components/SelectedSeats.vue'
import type { Seat, TicketEvent, TicketSession } from '../types'

defineProps<{
  event: TicketEvent
  session: TicketSession
  seats: Seat[]
  selectedSeats: Seat[]
  selectedSeatIds: string[]
  loading: boolean
  busy: boolean
}>()

defineEmits<{
  back: []
  toggle: [seat: Seat]
  reserve: []
  refresh: []
  clear: []
}>()
</script>

<template>
  <main class="page-shell page-shell--wide">
    <button class="back-button" type="button" @click="$emit('back')">
      <ArrowLeft :size="17" aria-hidden="true" />
      返回选择场次
    </button>

    <section class="compact-context">
      <div>
        <p class="eyebrow">{{ event.category }}</p>
        <h1>{{ event.name }}</h1>
      </div>
      <div class="compact-context__meta">
        <span><CalendarDays :size="17" aria-hidden="true" />{{ session.date }} {{ session.weekday }} · {{ session.time }}</span>
        <span><MapPin :size="17" aria-hidden="true" />{{ session.venue }}</span>
      </div>
    </section>

    <div v-if="loading" class="seat-layout">
      <div class="seat-map-panel skeleton-card"></div>
      <div class="selection-panel skeleton-card"></div>
    </div>
    <div v-else class="seat-layout">
      <SeatGrid
        :seats="seats"
        :selected-seat-ids="selectedSeatIds"
        @toggle="$emit('toggle', $event)"
      />
      <SelectedSeats
        :selected-seats="selectedSeats"
        :session="session"
        :busy="busy"
        @remove="$emit('toggle', $event)"
        @reserve="$emit('reserve')"
        @refresh="$emit('refresh')"
        @clear="$emit('clear')"
      />
    </div>
  </main>
</template>
