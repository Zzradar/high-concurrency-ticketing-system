<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, CalendarDays, MapPin } from '@lucide/vue'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import SeatGrid from '../components/SeatGrid.vue'
import RecoverableCheckoutPanel from '../components/RecoverableCheckoutPanel.vue'
import SelectedSeats from '../components/SelectedSeats.vue'
import { routeNames } from '../navigation'
import type { CheckoutSession, Seat, SeatStatic, SeatZoneAvailabilitySummary, TicketEvent, TicketSession } from '../types'
import { countSeatStatuses } from '../utils/seatMap'

const props = defineProps<{
  event: TicketEvent
  session: TicketSession
  seats: Seat[]
  seatLayout: SeatStatic[]
  activeZone: string
  zoneSummaries: SeatZoneAvailabilitySummary[]
  selectedSeats: Seat[]
  selectedSeatIds: string[]
  checkoutSession: CheckoutSession | null
  recoverableCheckoutSessions: CheckoutSession[]
  loading: boolean
  refreshing: boolean
  availabilityWarning: string
  checkoutCreating: boolean
  checkoutSyncInFlight: boolean
  confirming: boolean
  submittingPolling: boolean
  submitUncertain: boolean
  editingDisabled: boolean
}>()

defineEmits<{
  changeZone: [zone: string]
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

const overallCounts = computed(() => props.zoneSummaries.reduce((counts,zone) => ({
  total:counts.total+zone.total,available:counts.available+zone.available,held:counts.held+zone.held,sold:counts.sold+zone.sold,
}),{total:0,available:0,held:0,sold:0}))
const visibleSeats = computed(() => props.seats)
const visibleCounts = computed(() => countSeatStatuses(visibleSeats.value))
const currentZoneName = computed(() => props.activeZone)
</script>

<template>
  <main class="page-shell page-shell--wide">
    <PageBreadcrumbs
      :items="[
        { label: '活动', to: { name: routeNames.events } },
        { label: event.name, to: { name: routeNames.eventSessions, params: { eventId: event.id } } },
        { label: session.date + ' ' + session.time },
        { label: '选座' },
      ]"
    />
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

    <section v-if="!loading && seats.length" class="seat-overview" aria-label="场次座位状态与区域筛选">
      <div class="seat-status-summary" aria-label="当前场次座位统计">
        <span><small>可选</small><strong>{{ overallCounts.available }}</strong></span>
        <span><small>锁定中</small><strong>{{ overallCounts.held }}</strong></span>
        <span><small>已售</small><strong>{{ overallCounts.sold }}</strong></span>
        <span><small>已选</small><strong>{{ selectedSeatIds.length }} / 6</strong></span>
      </div>
      <div class="zone-browser" role="group" aria-label="按座位区域浏览">
        <button
          v-for="zone in zoneSummaries"
          :key="zone.zone"
          type="button"
          :class="{ 'is-active': activeZone === zone.zone }"
          :aria-pressed="activeZone === zone.zone"
          @click="$emit('changeZone', zone.zone)"
        >
          <strong>{{ zone.zone }}</strong><span>可选 {{ zone.available }} · 共 {{ zone.total }}</span>
        </button>
      </div>
    </section>

    <p v-if="availabilityWarning" class="availability-warning" role="status">
      {{ availabilityWarning }} 已保留当前座位图，你仍可查看已有状态。
    </p>

    <div v-if="loading" class="seat-layout">
      <div class="seat-map-panel skeleton-card"></div>
      <div class="selection-panel skeleton-card"></div>
    </div>
    <PageState
      v-else-if="!seats.length"
      eyebrow="SEAT MAP"
      title="当前场次暂无座位信息"
      description="座位图尚未开放，请返回场次列表选择其他场次。"
    />
    <RecoverableCheckoutPanel
      v-else-if="recoverableCheckoutSessions.length"
      :sessions="recoverableCheckoutSessions"
      :seats="seatLayout"
      @continue="$emit('continueCheckout', $event)"
      @abandon="$emit('abandonCheckout', $event)"
      @start-new="$emit('startNewCheckout')"
    />
    <div v-else class="seat-layout">
      <SeatGrid
        :seats="visibleSeats"
        :selected-seat-ids="selectedSeatIds"
        :editing-disabled="editingDisabled"
        :zone-name="currentZoneName"
        :available-count="visibleCounts.available"
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
        :refreshing="refreshing"
        @remove="$emit('toggle', $event)"
        @reserve="$emit('reserve')"
        @refresh="$emit('refresh')"
        @clear="$emit('clear')"
        @retry-confirm="$emit('retryConfirm')"
      />
    </div>
  </main>
</template>
