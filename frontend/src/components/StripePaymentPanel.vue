<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { Stripe, StripeElements, StripePaymentElement } from '@stripe/stripe-js'
import { getStripe, missingStripeKey, unavailableStripe } from '../payments/stripeClient'
import { paymentReturnUrl } from '../payments/paymentReturn'

const props = defineProps<{ clientSecret: string; paymentAttemptId: string; orderId: string; disabled?: boolean }>()
const emit = defineEmits<{ submitted: [attemptId: string, uncertain: boolean] }>()
const container = ref<HTMLElement | null>(null)
const stripeElementLoading = ref(true)
const stripeConfirming = ref(false)
const complete = ref(false)
const message = ref('')
let stripe: Stripe | undefined
let elements: StripeElements | undefined
let paymentElement: StripePaymentElement | undefined
let generation = 0

function destroy() {
  generation++
  paymentElement?.destroy()
  paymentElement = undefined
  elements = undefined
  stripe = undefined
}

watch(() => [props.clientSecret, props.paymentAttemptId, props.orderId, container.value], async () => {
  destroy()
  const current = generation
  stripeElementLoading.value = true
  stripeConfirming.value = false
  complete.value = false
  message.value = ''
  if (!container.value) return
  try {
    const client = await getStripe()
    if (current !== generation) return
    stripe = client
    elements = client.elements({ clientSecret: props.clientSecret })
    paymentElement = elements.create('payment')
    paymentElement.on('ready', () => { if (current === generation) stripeElementLoading.value = false })
    paymentElement.on('change', (event) => { if (current === generation) complete.value = event.complete })
    paymentElement.on('loaderror', () => {
      if (current !== generation) return
      message.value = unavailableStripe
      stripeElementLoading.value = false
      complete.value = false
    })
    paymentElement.mount(container.value)
  } catch (cause) {
    if (current !== generation) return
    message.value = cause instanceof Error && cause.message === missingStripeKey ? missingStripeKey : unavailableStripe
    stripeElementLoading.value = false
  }
}, { flush: 'post', immediate: true })

async function confirm() {
  if (!stripe || !elements || !complete.value || stripeElementLoading.value || stripeConfirming.value || props.disabled) return
  const current = generation
  const attemptId = props.paymentAttemptId
  stripeConfirming.value = true
  message.value = ''
  try {
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: paymentReturnUrl(props.orderId, attemptId) },
      redirect: 'if_required',
    })
    if (current !== generation) return
    if (result.error && ['validation_error', 'card_error'].includes(result.error.type)) {
      // Only user-correctable messages, with defensive redaction; never expose raw errors.
      message.value = (result.error.message || '请检查支付信息后重试。')
        .split(props.clientSecret).join('[已隐藏]')
        .replace(/\b(?:pi|seti)_\S*_secret_\S+/g, '[已隐藏]')
      stripeConfirming.value = false
      return
    }
    emit('submitted', attemptId, Boolean(result.error) || !result.paymentIntent)
  } catch {
    if (current === generation) emit('submitted', attemptId, true)
  }
}

onBeforeUnmount(destroy)
</script>

<template>
  <section class="stripe-payment-panel" aria-label="支付方式">
    <h2>支付方式</h2>
    <p>当前支付尝试：{{ paymentAttemptId }}</p>
    <p v-if="stripeElementLoading" role="status">正在加载支付组件…</p>
    <div ref="container"></div>
    <p v-if="message" role="alert">{{ message }}</p>
    <button class="primary-button" type="button" :disabled="disabled || stripeElementLoading || stripeConfirming || !complete" @click="confirm">
      {{ stripeConfirming ? '正在与支付渠道确认…' : '确认支付' }}
    </button>
  </section>
</template>

<style scoped>
.stripe-payment-panel { margin-top: 24px; padding: 24px; background: white; border: 1px solid #deded9; border-radius: 16px; }
.stripe-payment-panel h2 { margin: 0 0 12px; }
.stripe-payment-panel p { overflow-wrap: anywhere; }
.stripe-payment-panel button { margin-top: 18px; }
</style>
