import { readonly, ref } from 'vue'
import { onUnauthenticated, ticketApi, TicketApiError } from '../api/ticketApi'
import type { CurrentUser } from '../types'

const currentUserState = ref<CurrentUser | null>(null)
const authLoadingState = ref(false)
let initialized = false

function clearAuth() {
  currentUserState.value = null
}

onUnauthenticated(clearAuth)

async function refreshMe() {
  authLoadingState.value = true
  try {
    currentUserState.value = await ticketApi.me()
  } catch (error) {
    if (!(error instanceof TicketApiError && error.code === 'UNAUTHENTICATED')) {
      // Authentication availability is retried on the next protected navigation.
    }
    clearAuth()
  } finally {
    initialized = true
    authLoadingState.value = false
  }
  return currentUserState.value
}

async function ensureAuthLoaded() {
  if (!initialized) await refreshMe()
  return currentUserState.value
}

async function login(username: string, password: string) {
  const previous = currentUserState.value?.id
  const user = await ticketApi.login(username, password)
  if (previous && previous !== user.id) {
    sessionStorage.removeItem(`ticketing.checkout.${previous}`)
  }
  currentUserState.value = user
  initialized = true
  return user
}

async function logout() {
  const userId = currentUserState.value?.id
  try {
    await ticketApi.logout()
  } finally {
    if (userId) sessionStorage.removeItem(`ticketing.checkout.${userId}`)
    clearAuth()
  }
}

export const authState = {
  currentUser: readonly(currentUserState),
  authLoading: readonly(authLoadingState),
  login,
  logout,
  refreshMe,
  ensureAuthLoaded,
  clearAuth,
}

export function checkoutLocatorKey() {
  const userId = currentUserState.value?.id
  return userId ? `ticketing.checkout.${userId}` : null
}
