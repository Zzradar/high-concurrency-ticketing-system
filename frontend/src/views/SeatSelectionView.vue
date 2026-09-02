<script setup lang="ts">
import { ArrowLeft, CalendarDays, MapPin } from '@lucide/vue'
import SeatGrid from '../components/SeatGrid.vue'
import RecoverableCheckoutPanel from '../components/RecoverableCheckoutPanel.vue'
import SelectedSeats from '../components/SelectedSeats.vue'
import type { CheckoutSession, Seat, TicketEvent, TicketSession } from '../types'

defineProps<{
  event: TicketEvent
  session: TicketSession
  seats: Seat[]
  selectedSeats: Seat[]
  selectedSeatIds: string[]
  checkoutSession: CheckoutSession | null
  recoverableCheckoutSessions: CheckoutSession[]
  loading: boolean
  checkoutCreating: boolean
  checkoutSyncInFlight: boolean
  confirming: boolean
  submittingPolling: boolean
  submitUncertain: boolean
  editingDisabled: boolean
}>()

defineEmits<{
  back: []
  toggle: [seat: Seat]
  reserve: []
  refresh: []
  clear: []
  continueCheckout: [checkout: CheckoutSession]
  abandonCheckout: [checkout: CheckoutSession]
  startNewCheckout: []
  retryConfirm: []
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
    <RecoverableCheckoutPanel
      v-else-if="recoverableCheckoutSessions.length"
      :sessions="recoverableCheckoutSessions"
      :seats="seats"
      @continue="$emit('continueCheckout', $event)"
      @abandon="$emit('abandonCheckout', $event)"
      @start-new="$emit('startNewCheckout')"
    />
    <div v-else class="seat-layout">
      <SeatGrid
        :seats="seats"
        :selected-seat-ids="selectedSeatIds"
        :editing-disabled="editingDisabled"
        @toggle="$emit('toggle', $event)"
      />
      <SelectedSeats
        :selected-seats="selectedSeats"
        :session="session"
        :checkout-status="checkoutSession?.status"
        :checkout-creating="checkoutCreating"
        :checkout-sync-in-flight="checkoutSyncInFlight"
        :confirming="confirming"
        :submitting-polling="submittingPolling"
        :submit-uncertain="submitUncertain"
        :editing-disabled="editingDisabled"
        @remove="$emit('toggle', $event)"
        @reserve="$emit('reserve')"
        @refresh="$emit('refresh')"
        @clear="$emit('clear')"
        @retry-confirm="$emit('retryConfirm')"
      />
    </div>
  </main>
</template>
