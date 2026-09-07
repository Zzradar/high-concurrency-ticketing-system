import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const loadStripe = vi.hoisted(() => vi.fn())
vi.mock('@stripe/stripe-js', () => ({ loadStripe }))
beforeEach(() => { vi.resetModules(); loadStripe.mockReset(); vi.stubEnv('VITE_STRIPE_PUBLISHABLE_KEY', 'pk_test_unit') })
afterEach(() => { vi.unstubAllEnvs() })

it('loads lazily and caches one promise for concurrent callers', async () => {
  const stripe = { elements: vi.fn() }
  loadStripe.mockResolvedValue(stripe)
  const { getStripe } = await import('./stripeClient')
  expect(loadStripe).not.toHaveBeenCalled()
  const first = getStripe()
  expect(getStripe()).toBe(first)
  expect(await first).toBe(stripe)
  expect(loadStripe).toHaveBeenCalledExactlyOnceWith('pk_test_unit')
})
it.each([null, 'reject'])('sanitizes unavailable Stripe (%s) and avoids repeated loads', async (result) => {
  if (result === 'reject') loadStripe.mockRejectedValue(new Error('sensitive raw provider details'))
  else loadStripe.mockResolvedValue(null)
  const { getStripe, unavailableStripe } = await import('./stripeClient')
  await expect(getStripe()).rejects.toThrow(unavailableStripe)
  await expect(getStripe()).rejects.toThrow(unavailableStripe)
  expect(loadStripe).toHaveBeenCalledOnce()
})
it('does not load Stripe without a publishable key', async () => {
  vi.stubEnv('VITE_STRIPE_PUBLISHABLE_KEY', '   ')
  const { getStripe, missingStripeKey } = await import('./stripeClient')
  await expect(getStripe()).rejects.toThrow(missingStripeKey)
  expect(loadStripe).not.toHaveBeenCalled()
})
