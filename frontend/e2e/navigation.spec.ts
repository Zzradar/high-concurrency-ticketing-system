import { expect, test } from '@playwright/test'

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
