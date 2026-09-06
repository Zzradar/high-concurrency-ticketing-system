<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

defineProps<{
  items: Array<{ label: string; to?: RouteLocationRaw }>
}>()
</script>

<template>
  <nav class="breadcrumbs" aria-label="页面层级">
    <template v-for="(item, index) in items" :key="index">
      <ChevronRight v-if="index" :size="13" aria-hidden="true" />
      <RouterLink v-if="item.to" :to="item.to">{{ item.label }}</RouterLink>
      <span v-else aria-current="page">{{ item.label }}</span>
    </template>
  </nav>
</template>
