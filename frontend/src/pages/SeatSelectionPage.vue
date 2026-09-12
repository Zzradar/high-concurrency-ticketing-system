<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authState, checkoutLocatorKey } from '../auth/authState'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import PageBreadcrumbs from '../components/PageBreadcrumbs.vue'
import PageState from '../components/PageState.vue'
import { routeNames, setPageTitle } from '../navigation'
import { requestNotificationRefresh, showNotice } from '../uiSignals'
import { useSalesWindow } from '../utils/salesWindow'
import { nextPollDelay } from '../utils/pollingPolicy'
import { ZoneAvailabilityState } from '../utils/zoneAvailability'
import SeatSelectionView from '../views/SeatSelectionView.vue'
import type { CheckoutSession, Seat, SeatStatic, TicketEvent, TicketOrder, TicketSession, SeatZoneAvailabilitySummary } from '../types'

const route = useRoute()
const router = useRouter()
const event = ref<TicketEvent | null>(null)
const session = ref<TicketSession | null>(null)
const seats = ref<Seat[]>([])
const seatLayout = ref<SeatStatic[]>([])
const seatMapLoaded = ref(false)
const selectedSeatIds = ref<string[]>([])
const checkout = ref<CheckoutSession | null>(null)
const recoverable = ref<CheckoutSession[]>([])
const sessionOrders = ref<TicketOrder[]>([])
const loading = ref(true)
const syncing = ref(false)
const refreshing = ref(false)
const confirming = ref(false)
const submittingPolling = ref(false)
const submitUncertain = ref(false)
const error = ref('')
const availabilityWarning = ref('')
let pollingGeneration = 0
const activeZone = ref('')
const zoneSummaries = ref<SeatZoneAvailabilitySummary[]>([])
let availability = new ZoneAvailabilityState([])
let availabilityEpoch = 0
let pageLoadEpoch = 0
let availabilityTimer: ReturnType<typeof setTimeout> | undefined
let ownContext = ''
let disposed = false
const zoneRequests = new Map<string, Promise<boolean>>()
let refreshWork: Promise<boolean> | undefined
let queuedRefresh = false
let queuedSnapshot = false
let activeRefreshEpoch = -1
let activeSnapshot = false
let wasHidden = document.hidden
let focusNeedsRead = true
function handleBlur() { focusNeedsRead = true }
let foregroundTimer: ReturnType<typeof setTimeout> | undefined
let pollAfterMs = 2000
let emptyStreak = 0
let errorStreak = 0
let retryAfterMs: number | undefined
function resetPolling() { emptyStreak = 0; errorStreak = 0; retryAfterMs = undefined; pollAfterMs = 2000 }
const salesOpen = computed(() => session.value?.salesWindow.state === 'OPEN' && session.value.status === 'ON_SALE' && event.value?.status === 'ON_SALE')
const { label: salesLabel } = useSalesWindow(computed(() => session.value?.salesWindow), refreshSalesSession)
async function refreshSalesSession() {
  if (!session.value) return
  const id = session.value.id
  const epoch = pageLoadEpoch
  const fresh = await ticketApi.getSession(id)
  if (disposed || epoch !== pageLoadEpoch || session.value?.id !== id) return
  session.value = fresh
  if (salesOpen.value) scheduleAvailability()
  else stopAvailabilityTimer()
}
async function handleSalesFailure(cause: unknown) {
  if (!(cause instanceof TicketApiError) || !['SALES_NOT_STARTED', 'SALES_ENDED'].includes(cause.code)) return false
  pollingGeneration++
  submittingPolling.value = false
  submitUncertain.value = false
  stopAvailabilityTimer()
  error.value = cause.code === 'SALES_NOT_STARTED' ? '售票尚未开始。' : '售票已结束。'
  try { await refreshSalesSession() } catch { /* Keep the map and fail closed until a successful read. */
    if (session.value) session.value = {...session.value, salesWindow: {...session.value.salesWindow, state: cause.code === 'SALES_ENDED' ? 'ENDED' : 'NOT_STARTED'}}
  }
  if (checkout.value?.status === 'SELECTING') {
    try { await ticketApi.abandonCheckoutSession(checkout.value.id) } catch { /* best effort */ }
  }
  checkout.value = null
  selectedSeatIds.value = []
  locatorClear()
  return true
}

function stopAvailabilityTimer() {
  if (availabilityTimer !== undefined) clearTimeout(availabilityTimer)
  availabilityTimer = undefined
}
function scheduleAvailability() {
  stopAvailabilityTimer()
  if (disposed || document.hidden || !salesOpen.value || !seatMapLoaded.value || !activeZone.value) return
  if (refreshWork) return
  availabilityTimer = setTimeout(() => { void refreshSeats(false) }, nextPollDelay({pollAfterMs,emptyStreak,errorStreak,retryAfterMs}))
}
async function syncZone(zone: string, force: boolean, epoch: number): Promise<boolean> {
  while (zoneRequests.has(zone)) {
    try { await zoneRequests.get(zone) } catch { /* next request may recover */ }
  }
  if (disposed || document.hidden || epoch !== availabilityEpoch || !session.value) return false
  const sessionId = session.value.id
  const owner = checkout.value?.id
  const work = (async () => {
    let more = true
    while (more) {
      if (document.hidden || disposed || epoch !== availabilityEpoch) return false
      const state = availability.sync.get(zone)
      const cursor = !force && state?.generation && state.cursor ? {generation:state.generation,since:state.cursor} : {}
      const response = await ticketApi.getSeatAvailability(sessionId,owner,{zone,...cursor})
      if (disposed || epoch !== availabilityEpoch || session.value?.id !== sessionId) return false
      if (response.sessionId !== sessionId || response.zone !== zone) throw new Error('Mismatched zone response')
      if (response.hasMore && response.cursor === cursor.since) throw new Error('Availability cursor did not advance')
      availability.apply(response)
      pollAfterMs = response.pollAfterMs
      errorStreak = 0; retryAfterMs = undefined
      emptyStreak = response.mode === 'delta' && response.changes.length === 0 ? Math.min(6,emptyStreak+1) : 0
      seats.value = availability.seats()
      zoneSummaries.value = availability.summaries
      more = response.hasMore
      force = false
      if (more) await new Promise<void>(resolve => setTimeout(resolve,0))
    }
    return true
  })()
  zoneRequests.set(zone,work)
  try { return await work } finally { if (zoneRequests.get(zone) === work) zoneRequests.delete(zone) }
}
async function changeZone(zone: string) {
  if (zone === activeZone.value) return
  availabilityEpoch++
  activeZone.value = zone
  await refreshSeats()
}
function requestForeground() {
  if (disposed || document.hidden || foregroundTimer !== undefined) return
  foregroundTimer = setTimeout(() => { foregroundTimer=undefined; void refreshSeats(true) },0)
}
function visibilityChanged() {
  if (document.hidden) { wasHidden=true; focusNeedsRead=true; stopAvailabilityTimer(); if(foregroundTimer!==undefined)clearTimeout(foregroundTimer);foregroundTimer=undefined }
  else if (wasHidden) { wasHidden=false; focusNeedsRead=false; requestForeground() }
}

const selectedSeats = computed(() => seats.value.filter((seat) => selectedSeatIds.value.includes(seat.id)))
const editingDisabled = computed(() => !salesOpen.value || refreshing.value || syncing.value || confirming.value || submittingPolling.value || checkout.value?.status !== 'SELECTING' && !!checkout.value)
const existingOrder = computed(() => sessionOrders.value.find((order) => order.status === 'PENDING_PAYMENT') ?? sessionOrders.value.find((order) => order.status === 'PAID'))

function locatorWrite(value: CheckoutSession) {
  const key = checkoutLocatorKey()
  if (key) sessionStorage.setItem(key, JSON.stringify({ checkoutSessionId: value.id, sessionId: value.sessionId }))
}

function locatorClear() {
  const key = checkoutLocatorKey()
  if (key) sessionStorage.removeItem(key)
}

async function refreshSeats(authoritative = true): Promise<boolean> {
  if (!session.value || !seatMapLoaded.value || !activeZone.value || disposed || document.hidden) return false
  stopAvailabilityTimer()
  const context = (authState.currentUser.value?.id ?? '') + '|' + (checkout.value?.id ?? '')
  const changed = context !== ownContext
  if (changed) { ownContext = context; availabilityEpoch++; availability.sync.clear() }
  if (authoritative || changed) resetPolling()
  if (refreshWork) {
    if (activeRefreshEpoch !== availabilityEpoch || ((authoritative || changed) && !activeSnapshot)) {
      queuedRefresh = true; queuedSnapshot ||= authoritative || changed
    }
    return refreshWork
  }
  queuedSnapshot ||= authoritative || changed
  refreshWork = (async () => {
    let succeeded = false
    do {
      queuedRefresh = false
      const force = queuedSnapshot; queuedSnapshot = false
      const epoch = availabilityEpoch
      activeRefreshEpoch=epoch; activeSnapshot=force
      const zones = new Set([activeZone.value])
      if (force) for (const seat of seatLayout.value) if (selectedSeatIds.value.includes(seat.id)) zones.add(seat.zone)
      refreshing.value = true
      try {
        succeeded = true
        for (const zone of zones) if (!(await syncZone(zone,force,epoch))) { succeeded=false; break }
        if (epoch === availabilityEpoch && succeeded) availabilityWarning.value = ''
      } catch (cause) {
        succeeded = false
        if (epoch === availabilityEpoch) {
          errorStreak=Math.min(5,errorStreak+1)
          retryAfterMs=cause instanceof TicketApiError?cause.retryAfterMs:undefined
          availabilityWarning.value = '座位状态暂未刷新，请稍后重试。'
        }
      }
      // Yield after completion before another queued request; never overlap browser requests.
      if (queuedRefresh && !disposed && !document.hidden) await new Promise<void>(resolve=>setTimeout(resolve,0))
    } while (queuedRefresh && !disposed && !document.hidden)
    return succeeded
  })()
  try { return await refreshWork } finally {
    refreshWork=undefined; refreshing.value=false
    if (!disposed) scheduleAvailability()
  }
}

async function refreshSessionOrders() {
  if (!session.value || !authState.currentUser.value) {
    sessionOrders.value = []
    return
  }
  sessionOrders.value = await ticketApi.getOrders({ sessionId: session.value.id, limit: 20 })
}

async function activate(value: CheckoutSession) {
  checkout.value = value
  selectedSeatIds.value = [...value.seatIds]
  recoverable.value = []
  locatorWrite(value)
  const refreshed = await refreshSeats()
  if (value.status === 'RESERVED' && value.order) {
    showNotice('该购票会话此前已经确认，已同步现有订单。')
    await router.push({ name: routeNames.orderDetail, params: { orderId: value.order.id } })
  } else if (value.status === 'SUBMITTING') {
    startSubmittingPoll(value.id)
  }
  return refreshed
}

async function recoverCheckout() {
  if (!session.value || !authState.currentUser.value) return
  const key = checkoutLocatorKey()
  if (key) {
    try {
      const locator = JSON.parse(sessionStorage.getItem(key) ?? '{}') as { checkoutSessionId?: string; sessionId?: string }
      if (locator.sessionId === session.value.id && locator.checkoutSessionId) {
        const value = await ticketApi.getCheckoutSession(locator.checkoutSessionId)
        if (value.status !== 'ABANDONED') {
          await activate(value)
          return
        }
      }
    } catch {
      locatorClear()
    }
  }
  recoverable.value = await ticketApi.listRecoverableCheckoutSessions(session.value.id)
}

async function load() {
  const loadEpoch = ++pageLoadEpoch
  availabilityEpoch++
  stopAvailabilityTimer()
  loading.value = true
  error.value = ''
  availabilityWarning.value = ''
  seatMapLoaded.value = false
  seatLayout.value = []
  seats.value = []
  try {
    const sessionId = String(route.params.sessionId)
    const loadedSession = await ticketApi.getSession(sessionId)
    if (disposed || loadEpoch !== pageLoadEpoch) return
    session.value = loadedSession
    const [loadedEvent, layout] = await Promise.all([
      ticketApi.getEvent(session.value.eventId),
      ticketApi.getSeatLayout(sessionId),
    ])
    if (disposed || loadEpoch !== pageLoadEpoch) return
    event.value = loadedEvent
    seatLayout.value = layout
    availability = new ZoneAvailabilityState(layout)
    activeZone.value = layout[0]?.zone ?? ''
    zoneSummaries.value = []
    ownContext = ''
    seatMapLoaded.value = true
    if (activeZone.value && !(await refreshSeats())) { seatMapLoaded.value = false; throw new Error('Initial zone unavailable') }
    setPageTitle(event.value.name + ' · 选座')
    await Promise.all([recoverCheckout(), refreshSessionOrders()])
  } catch (cause) {
    if (disposed || loadEpoch !== pageLoadEpoch) return
    const resourceMissing = cause instanceof TicketApiError &&
      ['SESSION_NOT_FOUND', 'EVENT_NOT_FOUND'].includes(cause.code)
    error.value = resourceMissing ? cause.message : '座位图加载失败，请稍后重试。'
  } finally {
    if (loadEpoch === pageLoadEpoch) loading.value = false
  }
}

async function requireLogin() {
  if (authState.currentUser.value) return true
  await router.push({ name: routeNames.login, query: { redirect: route.fullPath } })
  return false
}

async function toggleSeat(seat: Seat) {
  if (!(await requireLogin()) || editingDisabled.value) return
  let next = selectedSeatIds.value.includes(seat.id)
    ? selectedSeatIds.value.filter((id) => id !== seat.id)
    : [...selectedSeatIds.value, seat.id]
  if (!selectedSeatIds.value.includes(seat.id) && seat.status !== 'AVAILABLE') return
  if (next.length > 6) {
    error.value = '每个订单最多选择 6 个座位。'
    return
  }
  syncing.value = true
  error.value = ''
  try {
    const value = checkout.value
      ? await ticketApi.replaceCheckoutSessionSeats(checkout.value.id, next, checkout.value.revision)
      : next.length && session.value
        ? await ticketApi.createCheckoutSession(session.value.id, next)
        : null
    if (value) {
      checkout.value = value
      selectedSeatIds.value = [...value.seatIds]
      locatorWrite(value)
    }
    await refreshSeats()
  } catch (cause) {
    if (await handleSalesFailure(cause)) return
    error.value = cause instanceof TicketApiError ? cause.message : '座位选择同步失败。'
    const isHoldConflict = cause instanceof TicketApiError && cause.code === 'SEAT_TEMPORARILY_HELD'
    let refreshed: boolean | undefined
    if (checkout.value) {
      try {
        const recovered = await ticketApi.getCheckoutSession(checkout.value.id)
        refreshed = await activate(recovered)
      } catch { /* keep visible state */ }
    }
    if (isHoldConflict) {
      if (refreshed === undefined) refreshed = await refreshSeats()
      error.value = refreshed
        ? '所选座位刚被其他用户临时锁定，座位状态已刷新，请重新选择。'
        : '所选座位刚被其他用户临时锁定，最新座位状态暂未取得，请点击“刷新座位状态”后重试。'
    }
  } finally {
    syncing.value = false
  }
}

async function clearSeats() {
  if (!checkout.value) return
  syncing.value = true
  try {
    checkout.value = await ticketApi.replaceCheckoutSessionSeats(checkout.value.id, [], checkout.value.revision)
    selectedSeatIds.value = []
    locatorWrite(checkout.value)
    await refreshSeats()
  } finally {
    syncing.value = false
  }
}

async function confirmCheckout() {
  if (!(await requireLogin()) || !checkout.value || !selectedSeatIds.value.length) return
  if (checkout.value.status === 'SELECTING' && !salesOpen.value) return
  confirming.value = true
  error.value = ''
  try {
    const result = await ticketApi.confirmCheckoutSession(checkout.value.id)
    checkout.value = result.checkoutSession
    locatorWrite(result.checkoutSession)
    const messages = {
      CONFIRMED_NOW: '订单创建成功，请在 15 分钟内支付。',
      REUSED_CONFIRMATION: '该购票会话已有确认正在进行，正在同步同一结果。',
      ALREADY_CONFIRMED: '该购票会话此前已经生成订单，已同步现有订单。',
    }
    showNotice(messages[result.disposition])
    requestNotificationRefresh()
    if (result.checkoutSession.order) {
      await router.push({
        name: routeNames.orderDetail,
        params: { orderId: result.checkoutSession.order.id },
      })
    }
  } catch (cause) {
    if (await handleSalesFailure(cause)) return
    error.value = cause instanceof TicketApiError ? cause.message : '确认结果暂时未知，正在恢复同一购票会话。'
    if (!(cause instanceof TicketApiError) || cause.status !== undefined && cause.status >= 500 || cause.code === 'INTERNAL_ERROR') startSubmittingPoll(checkout.value.id)
  } finally {
    confirming.value = false
  }
}

function startSubmittingPoll(id: string) {
  const generation = ++pollingGeneration
  submittingPolling.value = true
  submitUncertain.value = false
  const started = Date.now()
  const poll = async () => {
    if (generation !== pollingGeneration) return
    try {
      const value = await ticketApi.getCheckoutSession(id)
      checkout.value = value
      if (value.status === 'RESERVED' && value.order) {
        submittingPolling.value = false
        showNotice('该购票会话此前已经生成订单，已同步现有订单。')
        await router.push({ name: routeNames.orderDetail, params: { orderId: value.order.id } })
        return
      }
      if (value.status !== 'SUBMITTING') {
        submittingPolling.value = false
        await activate(value)
        return
      }
    } catch { /* unknown result remains recoverable */ }
    if (Date.now() - started >= 15000) {
      submittingPolling.value = false
      submitUncertain.value = true
      return
    }
    window.setTimeout(poll, 2000)
  }
  void poll()
}

async function abandon(value: CheckoutSession) {
  try {
    await ticketApi.abandonCheckoutSession(value.id)
    recoverable.value = recoverable.value.filter((item) => item.id !== value.id)
    locatorClear()
    await refreshSeats()
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '放弃购票会话失败。'
  }
}

async function handleFocus() {
  if (document.hidden) return
  if (wasHidden || focusNeedsRead) { wasHidden=false; focusNeedsRead=false; requestForeground() }
  await refreshSalesSession().catch(() => { /* existing state remains authoritative */ })
  requestNotificationRefresh()
  await refreshSessionOrders()
  if (checkout.value) {
    try { const fresh=await ticketApi.getCheckoutSession(checkout.value.id); if(checkout.value && (fresh.revision!==checkout.value.revision || fresh.status!==checkout.value.status))await activate(fresh) } catch { /* best effort */ }
  }
}

onMounted(() => {
  void load()
  window.addEventListener('focus', handleFocus)
  window.addEventListener('blur', handleBlur)
  document.addEventListener('visibilitychange', visibilityChanged)
})
onBeforeUnmount(() => {
  disposed = true
  if (foregroundTimer !== undefined) clearTimeout(foregroundTimer)
  pageLoadEpoch++
  availabilityEpoch++
  stopAvailabilityTimer()
  document.removeEventListener('visibilitychange', visibilityChanged)
  pollingGeneration += 1
  window.removeEventListener('focus', handleFocus)
  window.removeEventListener('blur', handleBlur)
})
watch(() => authState.currentUser.value?.id, () => { void refreshSeats() })
watch(() => route.params.sessionId, () => { pollingGeneration++; checkout.value = null; selectedSeatIds.value = []; void load() })
</script>

<template>
  <main v-if="!loading && error && (!event || !session || !seatMapLoaded)" class="page-shell">
    <PageBreadcrumbs
      :items="[
        { label: '活动', to: { name: routeNames.events } },
        { label: '选座' },
      ]"
    />
    <PageState eyebrow="SEAT MAP" title="无法打开选座页" :description="error" action-label="重新加载" @action="load" />
  </main>
  <p v-else-if="error" class="message-banner message-banner--error" role="alert">{{ error }}</p>
  <section v-if="existingOrder" class="message-banner" role="status">
    <span>{{ existingOrder.status === 'PENDING_PAYMENT' ? '你有本场次待支付订单' : '你已经购买过本场次' }}</span>
    <button type="button" @click="router.push({ name: routeNames.orderDetail, params: { orderId: existingOrder.id } })">查看订单</button><span>也可继续购票</span>
  </section>
  <p v-if="session" class="message-banner" role="status">{{ salesLabel }} · 开售 {{ session.salesWindow.startsAt }} · 截止 {{ session.salesWindow.endsAt }}</p>
  <SeatSelectionView
    v-if="event && session && seatMapLoaded"
    :event="event" :session="session" :seats="seats.filter(seat => seat.zone === activeZone)"
    :seat-layout="seatLayout" :active-zone="activeZone" :zone-summaries="zoneSummaries" @change-zone="changeZone" :selected-seats="selectedSeats"
    :selected-seat-ids="selectedSeatIds" :checkout-session="checkout"
    :recoverable-checkout-sessions="recoverable" :loading="loading"
    :refreshing="refreshing" :availability-warning="availabilityWarning"
    :checkout-creating="syncing && !checkout" :checkout-sync-in-flight="syncing"
    :confirming="confirming" :submitting-polling="submittingPolling"
    :submit-uncertain="submitUncertain" :editing-disabled="editingDisabled"
    @back="router.push({ name: routeNames.eventSessions, params: { eventId: session.eventId } })" @toggle="toggleSeat"
    @reserve="confirmCheckout" @refresh="refreshSeats(true)" @clear="clearSeats"
    @continue-checkout="activate" @abandon-checkout="abandon"
    @start-new-checkout="recoverable = []" @retry-confirm="confirmCheckout"
  />
</template>
