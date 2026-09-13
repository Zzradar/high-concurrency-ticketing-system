import axios from 'axios'
import { readonly, ref } from 'vue'
import { advanceAuthenticationEpoch, onUnauthenticated, ticketApi, TicketApiError } from '../api/ticketApi'
import type { CurrentUser } from '../types'

const currentUserState = ref<CurrentUser | null>(null)
const authLoadingState = ref(false)
let initialized = false
let authRevision = 0

function clearAuth() {
  authRevision++
  advanceAuthenticationEpoch()
  currentUserState.value = null
}

onUnauthenticated(clearAuth)

async function refreshMe() {
  const revision = authRevision
  authLoadingState.value = true
  try {
    const user = await ticketApi.me()
    if (revision === authRevision) currentUserState.value = user
  } catch (error) {
    if (!(error instanceof TicketApiError && error.code === 'UNAUTHENTICATED')) {
      // Authentication availability is retried on the next protected navigation.
    }
    if (revision === authRevision) clearAuth()
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
  authRevision++
  advanceAuthenticationEpoch()
  const previous = currentUserState.value?.id
  const user = await ticketApi.login(username, password)
  authRevision++
  advanceAuthenticationEpoch()
  if (previous && previous !== user.id) {
    sessionStorage.removeItem(`ticketing.checkout.${previous}`)
  }
  currentUserState.value = user
  initialized = true
  return user
}

async function logout() {
  const userId = currentUserState.value?.id
  // Stop every user-owned poll before waiting for a potentially slow logout POST.
  clearAuth()
  initialized = true
  if (userId) sessionStorage.removeItem(`ticketing.checkout.${userId}`)
  try {
    await ticketApi.logout()
    return { confirmed: true }
  } catch (error) {
    const expired = (error instanceof TicketApiError && (error.status === 401 || error.code === 'UNAUTHENTICATED')) ||
      (axios.isAxiosError(error) && error.response?.status === 401)
    return { confirmed: expired }
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
