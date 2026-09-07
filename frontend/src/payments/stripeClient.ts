import type { Stripe } from '@stripe/stripe-js'

export const missingStripeKey = '支付组件配置错误：缺少 VITE_STRIPE_PUBLISHABLE_KEY，请联系管理员；可刷新订单状态。'
export const unavailableStripe = '支付组件暂时无法加载，请刷新页面后重试。'
let stripePromise: Promise<Stripe> | undefined

export function getStripe(): Promise<Stripe> {
  const key = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY?.trim()
  if (!key) return Promise.reject(new Error(missingStripeKey))
  // Import lazily too: simulation must never initiate Stripe.js network requests.
  stripePromise ??= import('@stripe/stripe-js').then(({ loadStripe }) => loadStripe(key))
    .then((stripe) => {
      if (!stripe) throw new Error(unavailableStripe)
      return stripe
    }).catch(() => { throw new Error(unavailableStripe) })
  return stripePromise
}
