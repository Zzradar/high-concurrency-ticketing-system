import { request, type APIRequestContext } from '@playwright/test'

export const BACKEND_URL = 'http://127.0.0.1:18080'
export const FRONTEND_ORIGIN = 'http://127.0.0.1:5173'
export const TEST_PASSWORD = 'Ticketing123!'

export type StorageState = Awaited<ReturnType<APIRequestContext['storageState']>>

export class AuthenticatedApi {
  private constructor(
    readonly context: APIRequestContext,
    readonly storageState: StorageState,
    private readonly csrfToken: string,
  ) {}

  static async login(username: string, password = TEST_PASSWORD) {
    const context = await request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Origin: FRONTEND_ORIGIN },
    })
    const response = await context.post('/auth/login', {
      data: { username, password },
    })
    if (!response.ok()) {
      throw new Error(`login failed for ${username}: ${response.status()} ${await response.text()}`)
    }
    const storageState = await context.storageState()
    const csrf = storageState.cookies.find((cookie) => cookie.name === 'ticketing_csrf')?.value
    if (!csrf) throw new Error(`login for ${username} did not return ticketing_csrf`)
    return new AuthenticatedApi(context, storageState, csrf)
  }

  private writeHeaders(extra: Record<string, string> = {}) {
    return {
      Origin: FRONTEND_ORIGIN,
      'X-CSRF-Token': this.csrfToken,
      ...extra,
    }
  }

  async createReservation(sessionId: string, seatId: string, idempotencyKey: string) {
    const response = await this.context.post('/reservations', {
      data: { sessionId, seatIds: [seatId] },
      headers: this.writeHeaders({ 'Idempotency-Key': idempotencyKey }),
    })
    if (response.status() !== 201) {
      throw new Error(`reservation arrange failed: ${response.status()} ${await response.text()}`)
    }
    return response.json()
  }

  async getSession(sessionId: string) {
    const response = await this.context.get(`/sessions/${sessionId}`)
    if (!response.ok()) throw new Error(`session read failed: ${response.status()}`)
    return response.json()
  }

  async dispose() {
    await this.context.dispose()
  }
}
