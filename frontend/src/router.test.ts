import { createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetMockData, setMockLatency } from './api/ticketApi'
import { authState } from './auth/authState'
import { routeNames } from './navigation'
import { appRoutes, createAppRouter } from './router'

describe('application router', () => {
  beforeEach(() => {
    resetMockData()
    setMockLatency(0)
    authState.clearAuth()
  })

  it('registers unique named routes, titles and a real not found page', () => {
    const routeNamesInTable = appRoutes.map((route) => route.name)
    expect(new Set(routeNamesInTable).size).toBe(routeNamesInTable.length)
    expect(routeNamesInTable).toEqual(expect.arrayContaining(Object.values(routeNames)))
    expect(appRoutes.find((route) => route.name === routeNames.notFound)?.redirect).toBeUndefined()
    expect(appRoutes.filter((route) => route.name !== routeNames.home).every((route) => route.meta?.title)).toBe(true)
  })

  it('resolves named navigation without hard-coded paths and updates the title', async () => {
    const testRouter = createAppRouter(createMemoryHistory())
    await testRouter.push({ name: routeNames.eventSessions, params: { eventId: 'event A/B' } })
    await testRouter.isReady()

    expect(testRouter.currentRoute.value.path).toBe('/events/event%20A%2FB/sessions')
    expect(testRouter.currentRoute.value.fullPath).toBe('/events/event%20A%2FB/sessions')
    expect(document.title).toBe('场次 | 票迹')
  })

  it('preserves the protected fullPath through the auth guard', async () => {
    const testRouter = createAppRouter(createMemoryHistory())
    await testRouter.push({
      name: routeNames.orderDetail,
      params: { orderId: 'TKT-1' },
      query: { source: 'notice' },
    })
    await testRouter.isReady()

    expect(testRouter.currentRoute.value.name).toBe(routeNames.login)
    expect(testRouter.currentRoute.value.query.redirect).toBe('/orders/TKT-1?source=notice')
  })

  it('keeps unknown URLs on the not found route', async () => {
    const testRouter = createAppRouter(createMemoryHistory())
    await testRouter.push('/missing/deep/path')
    await testRouter.isReady()

    expect(testRouter.currentRoute.value.name).toBe(routeNames.notFound)
    expect(testRouter.currentRoute.value.fullPath).toBe('/missing/deep/path')
    expect(document.title).toBe('页面不存在 | 票迹')
  })
})
