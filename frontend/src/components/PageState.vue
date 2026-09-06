<script setup lang="ts">
defineProps<{
  eyebrow?: string
  title: string
  description: string
  actionLabel?: string
}>()

defineEmits<{ action: [] }>()
</script>

<template>
  <section class="page-state" role="status">
    <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
    <h2>{{ title }}</h2>
    <p>{{ description }}</p>
    <button v-if="actionLabel" class="secondary-button" type="button" @click="$emit('action')">
      {{ actionLabel }}
    </button>
    <slot />
  </section>
</template>
