import { expect, test, type Page } from '@playwright/test'

// Test-only module overrides: no production fake Stripe globals or iframe emulation.
async function arrange(page: Page, scenario: 'stripe' | 'return' | 'simulation' | 'declined') {
  await page.goto('/events')
  return page.evaluate(async (scenario) => {
    const apiPath = '/src/api/ticketApi.ts'
    const routerPath = '/src/router.ts'
    const authPath = '/src/auth/authState.ts'
    const { ticketApi, setMockPaymentSimulation } = await import(/* @vite-ignore */ apiPath)
    const { router } = await import(/* @vite-ignore */ routerPath)
    const { authState } = await import(/* @vite-ignore */ authPath)
    await authState.login('demo', 'Ticketing123!')
    const { order } = await ticketApi.createReservation('ses-concert-1001', ['ses-concert-1001-A01'])
    if (scenario === 'simulation') setMockPaymentSimulation({ delayMilliseconds: 300, outcome: 'SUCCESS' })
    else {
      const attempt = { id: 'PAY-browser', orderId: order.id, provider: 'stripe', status: scenario === 'declined' ? 'FAILED' : 'SUCCEEDED', startedAt: new Date().toISOString(), processingDeadline: new Date(Date.now() + 10000).toISOString() }
      ticketApi.getPaymentAttempt = async (id: string) => {
        if (id !== attempt.id) throw new Error('unexpected attempt')
        return attempt
      }
      let payCalls = 0
      ticketApi.payOrder = async () => {
        payCalls++
        const id = scenario === 'declined' && payCalls > 1 ? 'PAY-browser-B' : attempt.id
        return { disposition: 'STARTED_NEW', order, paymentAttempt: { ...attempt, id, status: 'PROCESSING' }, paymentAction: { provider: 'stripe', type: 'CLIENT_CONFIRM', clientSecret: `pi_browser_${payCalls}_secret_memory` } }
      }
    }
    await router.push(`/orders/${order.id}` + (scenario === 'return' ? '?paymentReturn=1&paymentAttemptId=PAY-browser&payment_intent=pi_browser&payment_intent_client_secret=do_not_copy&redirect_status=succeeded' : ''))
    return order.id
  }, scenario)
}

test('Stripe action enters preparation UI safely without a configured key', async ({ page }) => {
  const stripeRequests: string[] = []
  page.on('request', (request) => { if (request.url().includes('stripe.com')) stripeRequests.push(request.url()) })
  await arrange(page, 'stripe')
  await page.getByRole('button', { name: /^模拟支付/ }).click()
  await expect(page.getByRole('region', { name: '支付方式' })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '缺少 VITE_STRIPE_PUBLISHABLE_KEY' })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认支付', exact: true })).toBeDisabled()
  expect(stripeRequests).toHaveLength(0)
  await page.getByRole('button', { name: '取消订单', exact: true }).click()
  await expect(page.getByRole('region', { name: '支付方式' })).toHaveCount(0)
})

test('payment return uses a local hint and cleans unused provider query', async ({ page }) => {
  const id = await arrange(page, 'return')
  await expect(page).toHaveURL(new RegExp(`/orders/${id}$`))
  await expect(page.getByRole('heading', { name: '待支付', exact: true })).toBeVisible()
  expect(await page.locator('body').innerText()).not.toContain('do_not_copy')
  const storage = await page.evaluate(() => [JSON.stringify(localStorage), JSON.stringify(sessionStorage)].join())
  expect(storage).not.toContain('do_not_copy')
})

test('simulation still reaches PAID without Stripe network access', async ({ page }) => {
  const stripeRequests: string[] = []
  page.on('request', (request) => { if (request.url().includes('stripe.com')) stripeRequests.push(request.url()) })
  await arrange(page, 'simulation')
  await page.getByRole('button', { name: /^模拟支付/ }).click()
  await expect(page.getByRole('heading', { name: '支付成功', exact: true })).toBeVisible()
  expect(stripeRequests).toHaveLength(0)
})

test('refresh after Backend failure destroys old preparation and allows a new Attempt', async ({ page }) => {
  await arrange(page, 'declined')
  await page.getByRole('button', { name: /^模拟支付/ }).click()
  await expect(page.getByRole('region', { name: '支付方式' })).toContainText('PAY-browser')
  await expect(page.getByRole('button', { name: '支付已准备' })).toBeDisabled()
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect(page.getByRole('region', { name: '支付方式' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '待支付', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^开始支付/ })).toBeEnabled()
  await page.getByRole('button', { name: /^开始支付/ }).click()
  await expect(page.getByRole('region', { name: '支付方式' })).toContainText('PAY-browser-B')
  await expect(page.getByRole('region', { name: '支付方式' })).toHaveCount(1)
})
