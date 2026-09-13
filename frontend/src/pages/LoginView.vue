<script setup lang="ts">
const showDemoCredentials = import.meta.env.DEV || import.meta.env.VITE_USE_MOCK_API === 'true'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authState } from '../auth/authState'
import { TicketApiError } from '../api/ticketApi'
import { routeNames } from '../navigation'
import { safeInternalRedirect } from '../utils/admissionContract'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

let mounted = true
let attempt: { controller: AbortController; revision: number } | null = null
onBeforeUnmount(() => { mounted = false; attempt?.controller.abort(); attempt = null })
watch(authState.operation, () => {
  if (attempt && attempt.revision !== authState.operation.value) {
    attempt.controller.abort()
    attempt = null
    busy.value = false
  }
}, { flush: 'sync' })

async function submit() {
  const old = attempt
  attempt = null
  old?.controller.abort()
  const controller = new AbortController()
  busy.value = true
  error.value = ''
  const result = authState.login(username.value, password.value, { signal: controller.signal })
  const own = { controller, revision: authState.operation.value }
  attempt = own
  const current = () => mounted && attempt === own && !controller.signal.aborted && own.revision === authState.operation.value
  try {
    const user = await result
    if (!user || !current()) return
    const redirect = safeInternalRedirect(route.query.redirect)
      ? route.query.redirect
      : { name: routeNames.events }
    await router.replace(redirect)
  } catch (cause) {
    if (current()) error.value = cause instanceof TicketApiError ? cause.message : '登录失败，请稍后重试。'
  } finally {
    if (current()) { busy.value = false; attempt = null }
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
      <small v-if="showDemoCredentials">开发演示账号：demo / Ticketing123!</small>
    </form>
  </main>
</template>
