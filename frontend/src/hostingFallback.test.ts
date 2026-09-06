import { describe, expect, it, vi } from 'vitest'
// The Sites runtime entry is plain JavaScript because it is copied verbatim from public/.
// @ts-expect-error no declaration file is needed for the deployment worker fixture
import worker from '../public/server/index.js'

describe('Sites SPA history fallback', () => {
  it('serves index.html when an HTML navigation does not match an asset', async () => {
    const fetch = vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname
      return path === '/index.html'
        ? new Response('<div id="app"></div>', { status: 200 })
        : new Response('missing', { status: 404 })
    })
    const response = await worker.fetch(
      new Request('https://example.test/sessions/session-1/seats', {
        headers: { accept: 'text/html,application/xhtml+xml' },
      }),
      { ASSETS: { fetch } },
    )

    expect(response.status).toBe(200)
    expect(await response.text()).toContain('id="app"')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(new URL(fetch.mock.calls[1]![0].url).pathname).toBe('/index.html')
  })

  it('preserves 404 responses for non-navigation asset requests', async () => {
    const fetch = vi.fn(async () => new Response('missing', { status: 404 }))
    const response = await worker.fetch(
      new Request('https://example.test/assets/missing.js', {
        headers: { accept: 'application/javascript' },
      }),
      { ASSETS: { fetch } },
    )

    expect(response.status).toBe(404)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
