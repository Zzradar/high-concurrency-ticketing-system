<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authState } from '../auth/authState'
import { TicketApiError } from '../api/ticketApi'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await authState.login(username.value, password.value)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
      ? route.query.redirect
      : '/events'
    await router.replace(redirect)
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '登录失败，请稍后重试。'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="page-shell auth-page">
    <form class="selection-panel auth-card" @submit.prevent="submit">
      <p class="eyebrow">WELCOME BACK</p><h1>登录票迹</h1>
      <label>用户名<input v-model="username" name="username" autocomplete="username" maxlength="64" required /></label>
      <label>密码<input v-model="password" name="password" type="password" autocomplete="current-password" maxlength="1024" required /></label>
      <p v-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</p>
      <button class="primary-button" type="submit" :disabled="busy">{{ busy ? '正在登录…' : '登录' }}</button>
      <small>开发演示账号：demo / Ticketing123!</small>
    </form>
  </main>
</template>
