import { row, sqlLiteral } from '../api/database'
import { AuthenticatedApi } from '../api/ticketing'
import { authenticatedContext, expect, test } from '../fixtures'

const EVENT_ID = 'perf-event-001'
const EVENT_NAME = 'Performance Event 1'
const SESSION_IDS = [1, 2, 3, 4].map((value) => `perf-session-001-${value.toString().padStart(3, '0')}`)
const sessionSeat = (sessionIndex: number, seatIndex: number) =>
  `perf-ss-001-${sessionIndex.toString().padStart(3, '0')}-${seatIndex.toString().padStart(6, '0')}`

test('different users converge after a real first-checkout seat hold conflict', async ({ browser }) => {
  const contender = await authenticatedContext(browser, 'perf-user-000006')
  let holder: Awaited<ReturnType<typeof authenticatedContext>> | undefined
  let holderCheckoutId = ''
  const sessionId = SESSION_IDS[0]
  const seatId = sessionSeat(1, 2)
  try {
    holder = await authenticatedContext(browser, 'perf-user-000005')
    const initialCounts = row(`SELECT
      count(*) FILTER (WHERE user_id = 'perf-user-000005'),
      count(*) FILTER (WHERE user_id = 'perf-user-000006')
      FROM checkout_sessions WHERE session_id = ${sqlLiteral(sessionId)};`)
    const page = await contender.context.newPage()
    const reads: URL[] = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname.startsWith(`/api/sessions/${sessionId}/seat`)) reads.push(url)
    })
    const count = (suffix: string) => reads.filter((url) => url.pathname.endsWith(suffix)).length
    await page.goto(`/sessions/${sessionId}/seats`)
    const target = page.getByRole('button', { name: /^R001-002，可选，/ })
    await expect(target).toBeEnabled()
    await expect(page.getByRole('button', { name: '刷新座位状态', exact: true })).toBeEnabled()
    expect(count('/seat-layout')).toBe(1)
    expect(count('/seat-availability')).toBe(1)
    // Observe a stable page long enough to catch an accidentally added short polling loop.
    await page.waitForTimeout(1500)
    expect(count('/seat-availability')).toBe(1)
    await page.getByRole('button', { name: '刷新座位状态', exact: true }).click()
    await expect(page.getByRole('button', { name: '刷新座位状态', exact: true })).toBeEnabled()
    expect(count('/seat-availability')).toBe(2)

    const held = await holder.api.createCheckoutSession(sessionId, [seatId])
    holderCheckoutId = held.id
    expect(held.status).toBe('SELECTING')
    expect(held.seatIds).toEqual([seatId])
    const conflictResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/checkout-sessions' &&
      response.request().method() === 'POST' && response.status() === 409,
    )
    await target.click()
    expect((await (await conflictResponse).json()).code).toBe('SEAT_TEMPORARILY_HELD')
    await expect(page.getByRole('button', { name: /^R001-002，锁定中，/ })).toBeDisabled()
    await expect(page.getByRole('alert')).toHaveText('所选座位刚被其他用户临时锁定，座位状态已刷新，请重新选择。')
    expect(count('/seat-availability')).toBe(3)
    expect(count('/seat-layout')).toBe(1)
    expect(count('/seats')).toBe(0)
    expect(reads.filter((url) => url.searchParams.has('checkoutSessionId'))).toHaveLength(0)
    await expect(page.locator('.selected-seat')).toHaveCount(0)
    expect(row(`SELECT
      count(*) FILTER (WHERE user_id = 'perf-user-000005'),
      count(*) FILTER (WHERE user_id = 'perf-user-000006')
      FROM checkout_sessions WHERE session_id = ${sqlLiteral(sessionId)};`))
      .toEqual([String(Number(initialCounts[0]) + 1), initialCounts[1]])
    expect(row(`SELECT user_id, status FROM checkout_sessions WHERE id = ${sqlLiteral(holderCheckoutId)};`))
      .toEqual(['perf-user-000005', 'SELECTING'])
    expect(row(`SELECT status, current_reservation_id IS NULL FROM session_seats WHERE id = ${sqlLiteral(seatId)};`))
      .toEqual(['AVAILABLE', 't'])
  } finally {
    try {
      if (holderCheckoutId && holder) await holder.api.abandonCheckoutSession(holderCheckoutId)
    } finally {
      await Promise.all([
        contender.context.close(), contender.api.dispose(),
        holder?.context.close(), holder?.api.dispose(),
      ])
    }
  }
})

test('checkout-smoke uses UI login and reaches a pending order', async ({ page }) => {
  const seatReadUrls: URL[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith(`/api/sessions/${SESSION_IDS[0]}/seat`)) {
      seatReadUrls.push(url)
    }
  })

  await page.goto('/login')
  await page.getByLabel('用户名').fill('demo')
  await page.getByLabel('密码').fill('Ticketing123!')
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await expect(page.getByRole('heading', { name: '这一场，值得亲临。' })).toBeVisible()
  await page.getByRole('button', { name: `查看场次 ${EVENT_NAME}` }).click()
  await expect(page.getByRole('heading', { name: EVENT_NAME })).toBeVisible()
  await page.getByRole('button', { name: /^进入选座 / }).first().click()
  await expect(page).toHaveURL(new RegExp(`/sessions/${SESSION_IDS[0]}/seats$`))
  await expect(page.getByRole('heading', { name: EVENT_NAME })).toBeVisible()
  await expect(page.getByRole('region', { name: '场次座位状态与区域筛选' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^R001-004，可选，/ })).toBeVisible()

  await expect.poll(() =>
    seatReadUrls.filter((url) => url.pathname.endsWith('/seat-layout')).length,
  ).toBe(1)
  await expect.poll(() =>
    seatReadUrls.filter((url) => url.pathname.endsWith('/seat-availability')).length,
  ).toBe(1)
  expect(seatReadUrls.filter((url) => url.pathname.endsWith('/seats'))).toHaveLength(0)

  await page.getByRole('button', { name: /^R001-004，可选，/ }).click()
  await expect(page.getByRole('button', { name: '移除座位 R001-004' })).toBeVisible()
  await expect.poll(() =>
    seatReadUrls.filter((url) => url.pathname.endsWith('/seat-availability')).length,
  ).toBeGreaterThanOrEqual(2)
  const checkoutLocator = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem('ticketing.checkout.U-1001') ?? '{}') as {
      checkoutSessionId?: string
    },
  )
  const checkoutAvailability = seatReadUrls.find(
    (url) => url.pathname.endsWith('/seat-availability') &&
      url.searchParams.has('checkoutSessionId'),
  )
  expect(checkoutAvailability?.searchParams.get('checkoutSessionId')).toBe(
    checkoutLocator.checkoutSessionId,
  )
  expect(seatReadUrls.filter((url) => url.pathname.endsWith('/seat-layout'))).toHaveLength(1)
  expect(seatReadUrls.filter((url) => url.pathname.endsWith('/seats'))).toHaveLength(0)

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

test('large seat rows keep both ends reachable and reset the viewport across zones', async ({ browser }) => {
  test.setTimeout(90_000)
  const { api, context } = await authenticatedContext(browser, 'perf-user-000004')
  let checkoutSessionId = ''
  try {
    const page = await context.newPage()
    await page.goto(`/sessions/${SESSION_IDS[0]}/seats`)
    await expect(page.getByRole('region', { name: '场次座位状态与区域筛选' })).toBeVisible()

    const grid = page.getByRole('group', { name: '场馆座位图' })
    const firstRow = grid.locator('.seat-row').first()
    const rowSeats = firstRow.getByRole('button')
    await expect(rowSeats).toHaveCount(500)
    const firstSeat = rowSeats.first()
    const lastSeat = rowSeats.last()
    await expect(firstSeat).toHaveAttribute('aria-label', /^R001-001，可选，/)
    await expect(lastSeat).toHaveAttribute('aria-label', /^R001-500，可选，/)

    const initialGeometry = await grid.evaluate((viewport) => {
      const first = viewport.querySelector<HTMLElement>('.seat-row .seat-item')!
      const viewportRect = viewport.getBoundingClientRect()
      const firstRect = first.getBoundingClientRect()
      return {
        scrollLeft: viewport.scrollLeft,
        clientWidth: viewport.clientWidth,
        scrollWidth: viewport.scrollWidth,
        viewportLeft: viewportRect.left,
        firstLeft: firstRect.left,
        firstRight: firstRect.right,
      }
    })
    expect(initialGeometry.scrollLeft).toBe(0)
    expect(initialGeometry.scrollWidth).toBeGreaterThan(initialGeometry.clientWidth)
    expect(initialGeometry.firstLeft).toBeGreaterThanOrEqual(initialGeometry.viewportLeft - 1)
    expect(initialGeometry.firstRight).toBeGreaterThan(initialGeometry.viewportLeft)

    await firstSeat.click()
    await expect(page.getByRole('button', { name: '移除座位 R001-001' })).toBeVisible()
    checkoutSessionId = await page.evaluate(() =>
      JSON.parse(sessionStorage.getItem('ticketing.checkout.perf-user-000004') ?? '{}')
        .checkoutSessionId ?? '',
    )
    expect(checkoutSessionId).toBeTruthy()

    const gridBox = await grid.boundingBox()
    expect(gridBox).not.toBeNull()
    await page.mouse.move(gridBox!.x + gridBox!.width / 2, gridBox!.y + gridBox!.height / 2)
    await page.mouse.wheel(initialGeometry.scrollWidth, 0)
    await expect.poll(() => grid.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)

    const endGeometry = await grid.evaluate((viewport) => {
      const last = viewport.querySelector<HTMLElement>('.seat-row .seat-item:last-child')!
      const viewportRect = viewport.getBoundingClientRect()
      const lastRect = last.getBoundingClientRect()
      return {
        scrollLeft: viewport.scrollLeft,
        maxScrollLeft: viewport.scrollWidth - viewport.clientWidth,
        viewportRight: viewportRect.right,
        lastLeft: lastRect.left,
        lastRight: lastRect.right,
      }
    })
    expect(endGeometry.scrollLeft).toBe(endGeometry.maxScrollLeft)
    expect(endGeometry.lastLeft).toBeLessThan(endGeometry.viewportRight)
    expect(endGeometry.lastRight).toBeLessThanOrEqual(endGeometry.viewportRight + 1)
    await lastSeat.click()
    await expect(page.getByRole('button', { name: '移除座位 R001-500' })).toBeVisible()

    await page.getByRole('button', { name: /^STANDARD 可选/ }).click()
    await expect.poll(() => grid.evaluate((element) => element.scrollLeft)).toBe(0)
    await expect(page.getByRole('button', { name: '移除座位 R001-001' })).toBeVisible()
    await expect(page.getByRole('button', { name: '移除座位 R001-500' })).toBeVisible()
    const standardFirst = grid.getByRole('button').first()
    await expect(standardFirst).toHaveAttribute('aria-label', /^R003-001，可选，/)
    await standardFirst.click()
    await expect(page.getByRole('button', { name: '移除座位 R003-001' })).toBeVisible()

    await page.setViewportSize({ width: 520, height: 800 })
    await page.getByRole('button', { name: /^全部 可选/ }).click()
    await expect.poll(() => grid.evaluate((element) => element.scrollLeft)).toBe(0)
    const narrowGeometry = await grid.evaluate((viewport) => {
      const first = viewport.querySelector<HTMLElement>('.seat-row .seat-item')!
      const viewportRect = viewport.getBoundingClientRect()
      const firstRect = first.getBoundingClientRect()
      return {
        firstLeft: firstRect.left,
        firstRight: firstRect.right,
        viewportLeft: viewportRect.left,
        bodyOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      }
    })
    expect(narrowGeometry.firstLeft).toBeGreaterThanOrEqual(narrowGeometry.viewportLeft - 1)
    expect(narrowGeometry.firstRight).toBeGreaterThan(narrowGeometry.viewportLeft)
    expect(narrowGeometry.bodyOverflow).toBeLessThanOrEqual(1)

    await firstSeat.focus()
    await expect(firstSeat).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('button', { name: '移除座位 R001-001' })).toHaveCount(0)
    await firstSeat.focus()
    await expect(firstSeat).toBeFocused()
    await page.keyboard.press('Space')
    await expect(page.getByRole('button', { name: '移除座位 R001-001' })).toBeVisible()
  } finally {
    if (checkoutSessionId) await api.abandonCheckoutSession(checkoutSessionId)
    await context.close()
    await api.dispose()
  }
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
