import { expect, test } from '@playwright/test'

for (const width of [1280, 820, 375, 320]) {
  test(`账户菜单和主导航在 ${width}px 可用`, async ({ page }) => {
    await page.setViewportSize({ width, height: 850 })
    await page.goto('/login')
    await page.getByLabel('用户名').fill('demo')
    await page.getByLabel('密码').fill('Ticketing123!')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    const navigation = page.getByRole('navigation', { name: '主要导航' })
    await expect(navigation.getByRole('link', { name: '活动', exact: true })).toHaveAttribute('aria-current', 'page')
    await expect(navigation.getByRole('link', { name: '我的订单' })).toBeVisible()
    const account = page.getByRole('button', { name: '账户菜单' })
    await account.click()
    const panel = page.getByRole('region', { name: '当前账户' })
    await expect(panel.getByText('demo', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(/\/events$/)
    const bounds = await panel.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
    await page.keyboard.press('Tab')
    await expect(panel.getByRole('link', { name: '我的订单' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(panel.getByRole('button', { name: '退出登录' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(account).toBeFocused()
    await expect(panel).toHaveCount(0)
    await account.click()
    await panel.getByRole('link', { name: '我的订单' }).click()
    await expect(page).toHaveURL(/\/orders$/)
    await expect(panel).toHaveCount(0)
    await expect(navigation.getByRole('link', { name: '我的订单' })).toHaveAttribute('aria-current', 'page')
    await page.getByRole('button', { name: '通知中心' }).click()
    const notification = page.getByRole('region', { name: '通知列表' })
    await expect(notification).toBeVisible()
    const notificationBounds = await notification.boundingBox()
    expect(notificationBounds!.x).toBeGreaterThanOrEqual(0)
    expect(notificationBounds!.x + notificationBounds!.width).toBeLessThanOrEqual(width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    await account.click()
    await expect(notification).toHaveCount(0)
    await panel.getByRole('button', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login$/)
  })
}

test('活动、场次、登录、选座和确认保持真实 URL', async ({ page }) => {
  await page.goto('/events')
  await expect(page).toHaveTitle('活动列表 | 票迹')
  await page.getByRole('button', { name: /查看场次/ }).first().click()
  await expect(page).toHaveURL(/\/events\/evt-concert-2026\/sessions$/)

  await page.getByRole('button', { name: /进入选座/ }).first().click()
  await expect(page).toHaveURL(/\/sessions\/ses-concert-1001\/seats$/)
  await page.getByRole('button', { name: /A01，可选/ }).click()
  await expect(page).toHaveURL(/\/login\?redirect=/)
  expect(new URL(page.url()).searchParams.get('redirect')).toBe('/sessions/ses-concert-1001/seats')

  await page.getByLabel('用户名').fill('demo')
  await page.getByLabel('密码').fill('Ticketing123!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/sessions\/ses-concert-1001\/seats$/)

  await page.getByRole('button', { name: /A01，可选/ }).click()
  await page.getByRole('button', { name: /看台 A 区/ }).click()
  await page.getByRole('button', { name: /C01，可选/ }).click()
  await expect(page.getByRole('button', { name: '移除座位 A01' })).toBeVisible()
  await expect(page.getByRole('button', { name: '移除座位 C01' })).toBeVisible()

  await page.getByRole('button', { name: '提交预订' }).click()
  await expect(page).toHaveURL(/\/orders\/TKT-/)
  await expect(page).toHaveTitle('订单详情 | 票迹')
})

test('选座深链可直接打开并刷新', async ({ page }) => {
  await page.goto('/sessions/ses-concert-1001/seats')
  await expect(page.getByRole('heading', { name: '星海回响 · 2026 巡演' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '全部区域' })).toBeVisible()
  await expect(page).toHaveTitle('星海回响 · 2026 巡演 · 选座 | 票迹')

  const smallRowCenterOffset = await page.locator('.seat-row__items').first().evaluate((row) => {
    const seats = row.querySelectorAll<HTMLElement>('.seat-item')
    const rowRect = row.getBoundingClientRect()
    const firstRect = seats[0]!.getBoundingClientRect()
    const lastRect = seats[seats.length - 1]!.getBoundingClientRect()
    return Math.abs(
      (firstRect.left + lastRect.right) / 2 - (rowRect.left + rowRect.right) / 2,
    )
  })
  expect(smallRowCenterOffset).toBeLessThanOrEqual(1)

  await page.reload()
  await expect(page).toHaveURL(/\/sessions\/ses-concert-1001\/seats$/)
  await expect(page.getByRole('heading', { name: '星海回响 · 2026 巡演' })).toBeVisible()
})

test('受保护订单深链和刷新保留完整 redirect', async ({ page }) => {
  await page.goto('/orders/TKT-DEEP-LINK?source=e2e')
  await expect(page).toHaveURL(/\/login\?redirect=/)
  expect(new URL(page.url()).searchParams.get('redirect')).toBe('/orders/TKT-DEEP-LINK?source=e2e')

  await page.reload()
  await expect(page).toHaveURL(/\/login\?redirect=/)
  expect(new URL(page.url()).searchParams.get('redirect')).toBe('/orders/TKT-DEEP-LINK?source=e2e')
  await expect(page.getByRole('heading', { name: '登录票迹' })).toBeVisible()
})

test('未知深链显示 Not Found 且不改写 URL', async ({ page }) => {
  await page.goto('/unknown/deep/path')
  await expect(page).toHaveURL(/\/unknown\/deep\/path$/)
  await expect(page).toHaveTitle('页面不存在 | 票迹')
  await expect(page.getByRole('heading', { name: '页面不存在' })).toBeVisible()
})
