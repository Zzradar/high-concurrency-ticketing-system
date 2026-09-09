import { expect, test, type Page } from '@playwright/test'

async function arrange(page: Page, outcome: 'SUCCEEDED' | 'FAILED') {
  await page.goto('/events')
  return page.evaluate(async (outcome) => {
    const apiPath = '/src/api/ticketApi.ts'
    const routerPath = '/src/router.ts'
    const authPath = '/src/auth/authState.ts'
    const { ticketApi, setMockPaymentSimulation, setMockRefundSimulation, setMockLatency } = await import(/* @vite-ignore */ apiPath)
    const { router } = await import(/* @vite-ignore */ routerPath)
    const { authState } = await import(/* @vite-ignore */ authPath)
    setMockLatency(0)
    setMockPaymentSimulation({ delayMilliseconds: 10, outcome: 'SUCCESS' })
    setMockRefundSimulation({ delayMilliseconds: 3000, outcome })
    await authState.login('demo', 'Ticketing123!')
    const { order } = await ticketApi.createReservation('ses-concert-1001', ['ses-concert-1001-A01'])
    await ticketApi.payOrder(order.id)
    await new Promise((resolve) => setTimeout(resolve, 30))
    await router.push(`/orders/${order.id}`)
    return order.id
  }, outcome)
}

for (const outcome of ['SUCCEEDED', 'FAILED'] as const) {
  test(`buyer refund confirms explicitly, restores on re-entry and reaches ${outcome}`, async ({ page }) => {
    // Fix fixture date independently of the machine's calendar; browser timers remain real.
    await page.clock.setFixedTime(new Date('2026-09-09T02:00:00Z'))
    const id = await arrange(page, outcome)
    const panel = page.getByRole('region', { name: '全额退款', exact: true })
    await page.getByRole('button', { name: '申请全额退款', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '确认申请全额退款' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('¥1,280')
    await expect(page.getByRole('button', { name: '暂不退款' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
    await page.getByRole('button', { name: '申请全额退款', exact: true }).click()
    await page.getByRole('button', { name: '确认退款', exact: true }).dblclick()
    await expect(panel).toContainText('退款处理中，完成前订单和座位权益仍然有效。')
    await expect(page.getByRole('button', { name: '申请全额退款', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '继续浏览活动' }).click()
    await page.getByRole('link', { name: '我的订单', exact: true }).click()
    await page.getByRole('button').filter({ hasText: id }).click()
    await expect(panel).toContainText('退款处理中')
    // Advance the mock authority clock; no test-only product controls are added.
    await page.clock.setFixedTime(new Date('2026-09-09T02:00:04Z'))
    await expect(panel).toContainText(outcome === 'SUCCEEDED' ? '退款已完成，订单已取消，原座位已释放。' : '退款失败，订单和座位权益仍然有效。当前版本不支持再次自动退款。')
    await expect(page.getByRole('heading', { name: outcome === 'SUCCEEDED' ? '订单已取消' : '支付成功', exact: true })).toBeVisible()
    await page.screenshot({ path: `test-results/refund-${outcome.toLowerCase()}.png`, fullPage: true })
  })
}
