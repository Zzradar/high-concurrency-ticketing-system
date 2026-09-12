import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { isSalesWindow } from './eventContract'
import type { SalesWindow } from '../types'

export function salesWindowAt(startsAt: string, endsAt: string, now: number): SalesWindow {
  return { startsAt, endsAt, evaluatedAt: new Date(now).toISOString(),
    state: Date.parse(endsAt) <= Date.parse(startsAt) || now >= Date.parse(endsAt) ? 'ENDED'
      : now < Date.parse(startsAt) ? 'NOT_STARTED' : 'OPEN' }
}

// The corrected clock is display-only. Only a fresh server OPEN response enables buying.
export function useSalesWindow(window: Ref<SalesWindow | undefined>, refresh: () => Promise<void>) {
  const now = ref(Date.now())
  let offset = 0
  let timer: ReturnType<typeof setInterval> | undefined
  const visited = new Set<string>()
  const label = computed(() => {
    const value = window.value
    if (!isSalesWindow(value)) return '售票信息暂不可用'
    if (value.state === 'ENDED') return '售票已结束'
    const boundary = Date.parse(value.state === 'NOT_STARTED' ? value.startsAt : value.endsAt)
    const seconds = Math.max(0, Math.ceil((boundary - now.value) / 1000))
    return value.state === 'NOT_STARTED' ? `距开售 ${seconds} 秒` : `距停售 ${seconds} 秒`
  })
  watch(window, value => {
    if (timer) clearInterval(timer)
    if (!isSalesWindow(value)) return
    offset = Date.parse(value.evaluatedAt) - Date.now()
    now.value = Date.now() + offset
    if (value.state === 'ENDED') return
    const boundary = value.state === 'NOT_STARTED' ? value.startsAt : value.endsAt
    const key = value.state + '|' + boundary
    const tick = () => {
      now.value = Date.now() + offset
      if (now.value >= Date.parse(boundary) && !visited.has(key)) {
        visited.add(key)
        void refresh().catch(() => { /* Focus or explicit refresh can retry; no boundary HTTP loop. */ })
      }
    }
    timer = setInterval(tick, 1000)
    tick()
  }, { immediate: true })
  onBeforeUnmount(() => { if (timer) clearInterval(timer) })
  return { label }
}
