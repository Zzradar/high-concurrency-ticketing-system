import { expect, test as base, type Browser } from '@playwright/test'
import { AuthenticatedApi, TEST_PASSWORD } from '../api/ticketing'

export const test = base
export { expect }

export async function authenticatedContext(
  browser: Browser,
  username: string,
  password = TEST_PASSWORD,
) {
  const api = await AuthenticatedApi.login(username, password)
  const context = await browser.newContext({ storageState: api.storageState })
  return { api, context }
}
