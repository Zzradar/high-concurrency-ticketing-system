import type { LocationQuery } from 'vue-router'

const stripeQueryKeys = new Set(['payment_intent', 'payment_intent_client_secret', 'redirect_status'])
const returnQueryKeys = new Set([...stripeQueryKeys, 'paymentReturn', 'paymentAttemptId'])

export function cleanPaymentQuery(query: LocationQuery, includeHints = true): LocationQuery {
  const clean: LocationQuery = {}
  const excluded = includeHints ? returnQueryKeys : stripeQueryKeys
  // Only read values of unrelated keys, never the provider's secret query value.
  for (const key of Object.keys(query)) if (!excluded.has(key)) clean[key] = query[key]!
  return clean
}

export function hasStripeQuery(query: LocationQuery) {
  return Object.keys(query).some((key) => stripeQueryKeys.has(key))
}

export function paymentReturnUrl(orderId: string, attemptId: string) {
  return `${window.location.origin}/orders/${encodeURIComponent(orderId)}?paymentReturn=1&paymentAttemptId=${encodeURIComponent(attemptId)}`
}
