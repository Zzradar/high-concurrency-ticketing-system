<script setup lang="ts">
import { computed } from 'vue'
import { Armchair } from '@lucide/vue'
import SeatItem from './SeatItem.vue'
import type { Seat } from '../types'

const props = defineProps<{
  seats: Seat[]
  selectedSeatIds: string[]
  editingDisabled: boolean
}>()

defineEmits<{ toggle: [seat: Seat] }>()

const groupedRows = computed(() => {
  const rows = new Map<string, Seat[]>()
  props.seats.forEach((seat) => {
    if (!rows.has(seat.row)) rows.set(seat.row, [])
    rows.get(seat.row)!.push(seat)
  })
  return Array.from(rows.entries())
})
</script>

<template>
  <section class="seat-map-panel" aria-labelledby="seat-map-title">
    <div class="seat-map-panel__heading">
      <div>
        <p class="eyebrow">SEAT MAP</p>
        <h2 id="seat-map-title">选择你的座位</h2>
      </div>
      <p>点击空闲座位选择，再次点击取消</p>
    </div>

    <div class="seat-stage" aria-label="舞台位于座位图前方">
      <span>STAGE</span>
      <strong>舞台</strong>
    </div>

    <div class="seat-grid" role="group" aria-label="场馆座位图">
      <div v-for="[row, rowSeats] in groupedRows" :key="row" class="seat-row">
        <span class="seat-row__label">{{ row }}</span>
        <div class="seat-row__items">
          <SeatItem
            v-for="seat in rowSeats"
            :key="seat.id"
            :seat="seat"
            :selected="selectedSeatIds.includes(seat.id)"
            :editing-disabled="editingDisabled"
            @toggle="$emit('toggle', $event)"
          />
        </div>
        <span class="seat-row__label">{{ row }}</span>
      </div>
    </div>

    <div class="seat-legend" aria-label="座位状态说明">
      <span><i class="seat-legend__sample is-available"></i>可选择</span>
      <span><i class="seat-legend__sample is-selected"></i>已选择</span>
      <span><i class="seat-legend__sample is-held"></i>锁定中</span>
      <span><i class="seat-legend__sample is-sold"></i>已售出</span>
    </div>

    <div class="seat-map-note">
      <Armchair :size="18" aria-hidden="true" />
      座位状态以提交预订时服务端的最终确认为准
    </div>
  </section>
</template>
