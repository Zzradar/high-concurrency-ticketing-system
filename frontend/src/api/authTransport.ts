// Cookie mutations must finish in request order, including discarded-login cleanup.
let mutations: Promise<unknown> = Promise.resolve()
export function mutateAuthentication<T>(run: () => Promise<T>): Promise<T> {
  const result = mutations.then(run)
  mutations = result.catch(() => undefined)
  return result
}
export async function authenticationSettled() {
  let observed
  do { observed = mutations; await observed } while (observed !== mutations)
}
