<script setup lang="ts">
import type { Seat } from '../types'
import { formatCny } from '../utils/money'

const props = defineProps<{
  seat: Seat
  selected: boolean
}>()

const emit = defineEmits<{ toggle: [seat: Seat] }>()

function handleClick() {
  if (props.seat.status === 'AVAILABLE') emit('toggle', props.seat)
}

const statusLabel = {
  AVAILABLE: '可选',
  HELD: '锁定中',
  SOLD: '已售',
}
</script>

<template>
  <button
    :class="[
      'seat-item',
      'seat-item--' + seat.status.toLowerCase(),
      { 'seat-item--selected': selected },
    ]"
    type="button"
    :disabled="seat.status !== 'AVAILABLE'"
    :aria-pressed="selected"
    :aria-label="seat.label + '，' + (selected ? '已选择' : statusLabel[seat.status]) + '，' + formatCny(seat.price)"
    :title="seat.label + ' · ' + seat.zone + ' · ' + formatCny(seat.price)"
    @click="handleClick"
  >
    <span class="seat-item__back"></span>
    <span class="seat-item__label">{{ seat.number }}</span>
  </button>
</template>
