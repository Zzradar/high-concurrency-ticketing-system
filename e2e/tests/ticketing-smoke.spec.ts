import { row, sqlLiteral } from '../api/database'
import { AuthenticatedApi } from '../api/ticketing'
import { authenticatedContext, expect, test } from '../fixtures'

const EVENT_ID = 'perf-event-001'
const EVENT_NAME = 'Performance Event 1'
const SESSION_IDS = [1, 2, 3, 4].map((value) => `perf-session-001-${value.toString().padStart(3, '0')}`)
const sessionSeat = (sessionIndex: number, seatIndex: number) =>
  `perf-ss-001-${sessionIndex.toString().padStart(3, '0')}-${seatIndex.toString().padStart(6, '0')}`

test('checkout-smoke uses UI login and reaches a pending order', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('demo')
  await page.getByLabel('密码').fill('Ticketing123!')
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await expect(page.getByRole('heading', { name: '这一场，值得亲临。' })).toBeVisible()
  await page.getByRole('button', { name: `查看场次 ${EVENT_NAME}` }).click()
  await expect(page.getByRole('heading', { name: EVENT_NAME })).toBeVisible()
  await page.getByRole('button', { name: /^进入选座 / }).first().click()
  await expect(page.getByRole('heading', { name: '选择你的座位' })).toBeVisible()
  await page.getByRole('button', { name: /^R001-004，可选，/ }).click()
  await expect(page.getByRole('button', { name: '移除座位 R001-004' })).toBeVisible()
  await page.getByRole('button', { name: '提交预订' }).click()

  await expect(page.getByRole('heading', { name: '请确认并完成支付' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '待支付' })).toBeVisible()
  await expect(page.getByText('R001-004', { exact: true })).toBeVisible()
  const orderId = page.url().split('/orders/')[1]
  expect(orderId).toBeTruthy()
  expect(
    row(`
      SELECT checkout.status, reservation.status, ticket_order.status,
             seat.status, seat.current_reservation_id = reservation.id
      FROM checkout_sessions AS checkout
      JOIN reservations AS reservation ON reservation.id = checkout.reservation_id
      JOIN orders AS ticket_order ON ticket_order.reservation_id = reservation.id
      JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
      JOIN session_seats AS seat ON seat.id = item.session_seat_id
      WHERE checkout.user_id = 'U-1001'
        AND checkout.session_id = '${SESSION_IDS[0]}'
        AND ticket_order.id = ${sqlLiteral(orderId)};
    `),
  ).toEqual(['RESERVED', 'ACTIVE', 'PENDING_PAYMENT', 'HELD', 't'])
})

test('payment-smoke shows processing then the paid terminal state', async ({ browser }) => {
  const { api, context } = await authenticatedContext(browser, 'perf-user-000001')
  try {
    const created = await api.createReservation(
      SESSION_IDS[1], sessionSeat(2, 1), 'e2e-payment-smoke',
    )
    const page = await context.newPage()
    await page.goto(`/orders/${created.order.id}`)
    await expect(page.getByRole('heading', { name: '待支付' })).toBeVisible()
    await page.getByRole('button', { name: /^模拟支付/ }).click()
    await expect(page.getByRole('status').filter({ hasText: '支付渠道处理中' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '支付成功' })).toBeVisible({ timeout: 22_000 })
    await expect(page.getByRole('button', { name: /^模拟支付/ })).toHaveCount(0)
    expect(
      row(`
        SELECT ticket_order.status, reservation.status, seat.status,
               seat.current_reservation_id IS NULL,
               count(attempt.id) FILTER (WHERE attempt.accepted_at IS NOT NULL)
        FROM orders AS ticket_order
        JOIN reservations AS reservation ON reservation.id = ticket_order.reservation_id
        JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
        JOIN session_seats AS seat ON seat.id = item.session_seat_id
        LEFT JOIN payment_attempts AS attempt ON attempt.order_id = ticket_order.id
        WHERE ticket_order.id = ${sqlLiteral(created.order.id)}
        GROUP BY ticket_order.status, reservation.status, seat.status,
                 seat.current_reservation_id;
      `),
    ).toEqual(['PAID', 'CONFIRMED', 'SOLD', 't', '1'])
  } finally {
    await context.close()
    await api.dispose()
  }
})

test('order-deeplink restores authoritative details after reload', async ({ browser }) => {
  const { api, context } = await authenticatedContext(browser, 'perf-user-000002')
  try {
    const created = await api.createReservation(
      SESSION_IDS[2], sessionSeat(3, 1), 'e2e-order-deeplink',
    )
    const session = await api.getSession(SESSION_IDS[2])
    const page = await context.newPage()
    await page.goto(`/orders/${created.order.id}`)
    const assertDetails = async () => {
      await expect(page.getByText(created.order.id, { exact: true })).toBeVisible()
      await expect(page.getByRole('heading', { name: EVENT_NAME })).toBeVisible()
      await expect(page.getByText(`${session.date} ${session.weekday} · ${session.time}`, { exact: true })).toBeVisible()
      await expect(page.getByText('R001-001', { exact: true })).toBeVisible()
      await expect(page.getByRole('heading', { name: '待支付' })).toBeVisible()
    }
    await assertDetails()
    await page.reload()
    await assertDetails()
  } finally {
    await context.close()
    await api.dispose()
  }
})

test('multi-client converges two isolated contexts on one paid order', async ({ browser }) => {
  const first = await authenticatedContext(browser, 'perf-user-000003')
  const second = await authenticatedContext(browser, 'perf-user-000003')
  try {
    const firstToken = (await first.context.cookies()).find((cookie) => cookie.name === 'ticketing_session')?.value
    const secondToken = (await second.context.cookies()).find((cookie) => cookie.name === 'ticketing_session')?.value
    expect(firstToken).toBeTruthy()
    expect(secondToken).toBeTruthy()
    expect(firstToken).not.toBe(secondToken)

    const pageA = await first.context.newPage()
    const pageB = await second.context.newPage()
    const seatUrl = `/sessions/${SESSION_IDS[3]}/seats`
    await pageA.goto(seatUrl)
    await pageA.getByRole('button', { name: /^R001-001，可选，/ }).click()
    await expect(pageA.getByRole('button', { name: '移除座位 R001-001' })).toBeVisible()
    const locatorA = await pageA.evaluate(() => sessionStorage.getItem('ticketing.checkout.perf-user-000003'))
    expect(locatorA).toBeTruthy()

    await pageB.goto(seatUrl)
    await expect(pageB.getByRole('heading', { name: '发现可继续的购票会话' })).toBeVisible()
    expect(await pageB.evaluate(() => sessionStorage.getItem('ticketing.checkout.perf-user-000003'))).toBeNull()
    await pageB.getByRole('button', { name: '继续', exact: true }).click()
    await expect(pageB.getByRole('button', { name: '移除座位 R001-001' })).toBeVisible()
    const locatorB = await pageB.evaluate(() => sessionStorage.getItem('ticketing.checkout.perf-user-000003'))
    expect(locatorB).toBe(locatorA)

    await pageA.getByRole('button', { name: '提交预订' }).click()
    await pageA.waitForURL(/\/orders\//)
    const orderId = pageA.url().split('/orders/')[1]
    await pageB.reload()
    await pageB.waitForURL(new RegExp(`/orders/${orderId}$`))
    await expect(pageB.getByText(orderId, { exact: true })).toBeVisible()

    await pageA.getByRole('button', { name: /^模拟支付/ }).click()
    await expect(pageA.getByRole('heading', { name: '支付成功' })).toBeVisible({ timeout: 22_000 })
    await pageB.reload()
    await expect(pageB.getByRole('heading', { name: '支付成功' })).toBeVisible()
    expect(
      row(`
        SELECT count(DISTINCT reservation.id), count(DISTINCT ticket_order.id),
               count(DISTINCT attempt.id) FILTER (WHERE attempt.accepted_at IS NOT NULL),
               min(ticket_order.status), min(reservation.status)
        FROM reservations AS reservation
        JOIN orders AS ticket_order ON ticket_order.reservation_id = reservation.id
        LEFT JOIN payment_attempts AS attempt ON attempt.order_id = ticket_order.id
        WHERE reservation.user_id = 'perf-user-000003'
          AND reservation.session_id = '${SESSION_IDS[3]}';
      `),
    ).toEqual(['1', '1', '1', 'PAID', 'CONFIRMED'])
  } finally {
    await first.context.close()
    await second.context.close()
    await first.api.dispose()
    await second.api.dispose()
  }
})
