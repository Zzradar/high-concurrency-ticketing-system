import axios from 'axios'
import { readonly, ref } from 'vue'
import { advanceAuthenticationEpoch, onUnauthenticated, ticketApi, TicketApiError } from '../api/ticketApi'
import type { CurrentUser } from '../types'

const currentUserState = ref<CurrentUser | null>(null)
const authLoadingState = ref(false)
let initialized = false
const operation = ref(0)
let pendingLogin: number | null = null

function beginOperation() {
  operation.value++
  advanceAuthenticationEpoch()
  return operation.value
}

function clearAuth() {
  beginOperation()
  pendingLogin = null
  currentUserState.value = null
  initialized = true
  authLoadingState.value = false
}

onUnauthenticated(clearAuth)

async function refreshMe() {
  if (pendingLogin !== null) return currentUserState.value
  const revision = operation.value
  authLoadingState.value = true
  try {
    const user = await ticketApi.me()
    if (revision === operation.value) currentUserState.value = user
  } catch (error) {
    if (!(error instanceof TicketApiError && error.code === 'UNAUTHENTICATED')) {
      // Authentication availability is retried on the next protected navigation.
    }
    if (revision === operation.value) clearAuth()
  } finally {
    if (revision === operation.value) {
      initialized = true
      authLoadingState.value = false
    }
  }
  return currentUserState.value
}

async function ensureAuthLoaded() {
  if (!initialized) await refreshMe()
  return currentUserState.value
}

async function login(username: string, password: string, options: { signal?: AbortSignal } = {}) {
  const previous = currentUserState.value?.id
  const revision = beginOperation()
  pendingLogin = revision
  currentUserState.value = null
  initialized = false
  authLoadingState.value = true
  const current = () => revision === operation.value
  const cancel = () => { if (current() && pendingLogin === revision) clearAuth() }
  options.signal?.addEventListener('abort', cancel, { once: true })
  if (options.signal?.aborted) cancel()
  try {
    if (!current()) return null
    const user = await ticketApi.login(username, password, { isCurrent: current })
    if (!current()) return null
    if (previous && previous !== user.id) sessionStorage.removeItem(`ticketing.checkout.${previous}`)
    currentUserState.value = user
    initialized = true
    return user
  } catch (error) {
    if (!current()) return null
    initialized = true
    throw error
  } finally {
    options.signal?.removeEventListener('abort', cancel)
    if (current()) {
      pendingLogin = null
      authLoadingState.value = false
    }
  }
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
  operation: readonly(operation),
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
