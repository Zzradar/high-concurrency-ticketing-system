import { expect, it } from 'vitest'
import { cleanPaymentQuery, hasStripeQuery, paymentReturnUrl } from './paymentReturn'

it('removes provider secret by key without reading its value', () => {
  const query = { paymentReturn: '1', paymentAttemptId: 'P1', source: 'notice' }
  Object.defineProperty(query, 'payment_intent_client_secret', { enumerable: true, get() { throw new Error('must not read secret') } })
  expect(hasStripeQuery(query)).toBe(true)
  expect(cleanPaymentQuery(query, false)).toEqual({ paymentReturn: '1', paymentAttemptId: 'P1', source: 'notice' })
  expect(cleanPaymentQuery(query)).toEqual({ source: 'notice' })
})

it('encodes only local identities into the same-origin return URL', () => {
  expect(paymentReturnUrl('O/1', 'P?2&3')).toBe(`${window.location.origin}/orders/O%2F1?paymentReturn=1&paymentAttemptId=P%3F2%263`)
})
