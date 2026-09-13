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
import { admissionApi,admissionErrorText } from '../api/admissionApi'
import { AdmissionPolling } from '../utils/admissionPolling'
import RecoverableCheckoutPanel from '../components/RecoverableCheckoutPanel.vue'
import { nextPollDelay } from '../utils/pollingPolicy'
import { SingleFlight } from '../utils/singleFlight'
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
let submittingTimer: ReturnType<typeof setTimeout> | undefined
let submittingDeadline = 0, submittingEmpty = 0, submittingErrors = 0
let submittingRetry: number | undefined
let submittingVisibility = 0
let submittingWork: { generation: number; visible: number; promise: Promise<void> } | undefined
const checkoutReads = new SingleFlight<CheckoutSession>()
const focusReads = new SingleFlight<void>()
let lastFocusActivation = -Infinity
const activeZone = ref('')
const zoneSummaries = ref<SeatZoneAvailabilitySummary[]>([])
let availability = new ZoneAvailabilityState([])
let availabilityEpoch = 0
let pageLoadEpoch = 0
let availabilityTimer: ReturnType<typeof setTimeout> | undefined
let ownContext = ''
let disposed = false
let identityPaused = false
const zoneRequests = new Map<string, Promise<boolean>>()
let refreshWork: Promise<boolean> | undefined
let queuedRefresh = false
let queuedSnapshot = false
let activeRefreshEpoch = -1
let activeSnapshot = false
let wasHidden = document.hidden
let focusNeedsRead = true
function handleBlur() { focusNeedsRead = true; lastFocusActivation = -Infinity }
let foregroundTimer: ReturnType<typeof setTimeout> | undefined
let pollAfterMs = 2000
let emptyStreak = 0
let errorStreak = 0
let retryAfterMs: number | undefined
function resetPolling() { emptyStreak = 0; errorStreak = 0; retryAfterMs = undefined; pollAfterMs = 2000 }
const admissionBlocked = ref(false)
let leasePolling:AdmissionPolling|undefined
const formalAdmission = computed(()=>!!(session.value?.admission?.required || event.value?.admission?.required))
const salesOpen = computed(() => session.value?.salesWindow.state === 'OPEN' && session.value.status === 'ON_SALE' && event.value?.status === 'ON_SALE')
const { label: salesLabel } = useSalesWindow(computed(() => session.value?.salesWindow), refreshSalesSession)
function waitingTarget(){return {name:routeNames.waitingRoom,params:{eventId:session.value!.eventId},query:{sessionId:session.value!.id}}}
function enterWaitingRoom(){leasePolling?.stop();stopAvailabilityTimer();void router.replace(waitingTarget())}
function blockNewSelection(){
 admissionBlocked.value=true;availabilityEpoch++;stopAvailabilityTimer();leasePolling?.stop()
 if(!checkout.value && !recoverable.value.length)enterWaitingRoom()
}
async function ensureAdmission(){
 if(!formalAdmission.value){admissionBlocked.value=false;return true}
 if(session.value?.admission?.state==='UNAVAILABLE'||event.value?.admission?.state==='UNAVAILABLE')throw new TicketApiError('当前访问较多，请稍后重新加载。','ADMISSION_UNAVAILABLE',503)
 if(!authState.currentUser.value){void router.replace({name:routeNames.login,query:{redirect:router.resolve(waitingTarget()).fullPath}});return false}
 const expectedEpoch=pageLoadEpoch,expectedUser=authState.currentUser.value.id
 const state=await admissionApi.status(session.value!.eventId)
 if(disposed || expectedEpoch!==pageLoadEpoch || expectedUser!==authState.currentUser.value?.id)return false
 if(!['ADMITTED','NOT_REQUIRED'].includes(state.state)){blockNewSelection();return false}
 admissionBlocked.value=false
 leasePolling?.stop()
 if(state.state==='ADMITTED'){
  const eventId=session.value!.eventId
  leasePolling=new AdmissionPolling({leaseOnly:true,hidden:()=>document.hidden,
   request:(op,generation)=>op==='heartbeat'?admissionApi.heartbeat(eventId,generation!):admissionApi.status(eventId,generation),
   update:value=>{if(expectedEpoch===pageLoadEpoch&&expectedUser===authState.currentUser.value?.id&&!['ADMITTED','NOT_REQUIRED'].includes(value.state))blockNewSelection()},
   error:cause=>{availabilityWarning.value=admissionErrorText(cause)},
  });leasePolling.start(state)
 }
 return true
}
function isAdmissionFailure(cause:unknown){
 if(cause instanceof TicketApiError&&cause.code==='ADMISSION_REQUIRED'){blockNewSelection();return true}
 return false
}
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
  stopSubmitting()
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
  if (identityPaused || admissionBlocked.value || disposed || document.hidden || !salesOpen.value || !seatMapLoaded.value || !activeZone.value) return
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
  leasePolling?.visibility()
  if (document.hidden) { wasHidden=true; focusNeedsRead=true; lastFocusActivation=-Infinity; submittingVisibility++; clearTimeout(submittingTimer); stopAvailabilityTimer(); if(foregroundTimer!==undefined)clearTimeout(foregroundTimer);foregroundTimer=undefined }
  else if (wasHidden) { wasHidden=false; focusNeedsRead=false; requestForeground(); void handleFocus() }
}

const selectedSeats = computed(() => seats.value.filter((seat) => selectedSeatIds.value.includes(seat.id)))
const editingDisabled = computed(() => admissionBlocked.value || !salesOpen.value || refreshing.value || syncing.value || confirming.value || submittingPolling.value || checkout.value?.status !== 'SELECTING' && !!checkout.value)
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
  if (identityPaused || !session.value || !seatMapLoaded.value || !activeZone.value || disposed || document.hidden || admissionBlocked.value) return false
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
        if(isAdmissionFailure(cause))return false
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

function pageContext() {
  const page = pageLoadEpoch, user = authState.currentUser.value?.id
  return () => !disposed && page === pageLoadEpoch && user === authState.currentUser.value?.id
}
async function readCheckout(id: string) {
  const currentPage = pageContext(), generation = pollingGeneration, visible = submittingVisibility
  const current = () => currentPage() && generation === pollingGeneration && visible === submittingVisibility
  return checkoutReads.run(`${pageLoadEpoch}:${authState.currentUser.value?.id}:${generation}:${visible}:${id}`, () => ticketApi.getCheckoutSession(id), current)
}
async function refreshSessionOrders() {
  if (!session.value || !authState.currentUser.value) { sessionOrders.value = []; return }
  const current = pageContext(), id = session.value.id
  const values = await ticketApi.getOrders({ sessionId: id, limit: 20 })
  if (current() && session.value?.id === id) sessionOrders.value = values
}
async function activate(value: CheckoutSession) {
  const current = pageContext()
  if (!current() || value.userId !== authState.currentUser.value?.id || value.sessionId !== session.value?.id) return false
  if (value.status !== 'SUBMITTING') stopSubmitting()
  checkout.value = value
  selectedSeatIds.value = [...value.seatIds]
  recoverable.value = []
  locatorWrite(value)
  const refreshed = await refreshSeats()
  if (!current() || checkout.value?.id !== value.id) return false
  if (value.status === 'RESERVED' && value.order) {
    showNotice('该购票会话此前已经确认，已同步现有订单。')
    await router.push({ name: routeNames.orderDetail, params: { orderId: value.order.id } })
  } else if (value.status === 'SUBMITTING') startSubmittingPoll(value.id)
  return refreshed
}
async function recoverCheckout() {
  if (!session.value || !authState.currentUser.value) return
  const current = pageContext(), id = session.value.id, key = checkoutLocatorKey()
  if (key) {
    try {
      const locator = JSON.parse(sessionStorage.getItem(key) ?? '{}') as { checkoutSessionId?: string; sessionId?: string }
      if (locator.sessionId === id && locator.checkoutSessionId) {
        const value = await readCheckout(locator.checkoutSessionId)
        if (!current()) return
        if (value && value.status !== 'ABANDONED') { await activate(value); return }
      }
    } catch {
      if (!current()) return
      sessionStorage.removeItem(key)
    }
  }
  const values = await ticketApi.listRecoverableCheckoutSessions(id)
  if (current() && session.value?.id === id) recoverable.value = values
}

async function load() {
  identityPaused = false
  stopSubmitting()
  leasePolling?.stop();admissionBlocked.value=false
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
    if(formalAdmission.value){
      admissionBlocked.value=true
      await Promise.all([recoverCheckout(),refreshSessionOrders()])
      if(disposed || loadEpoch!==pageLoadEpoch || !(await ensureAdmission()) || loadEpoch!==pageLoadEpoch)return
    }
    if (activeZone.value && !document.hidden && !(await refreshSeats())) { if(admissionBlocked.value)return;seatMapLoaded.value = false; throw new Error('Initial zone unavailable') }
    setPageTitle(event.value.name + ' · 选座')
    if(!formalAdmission.value)await Promise.all([recoverCheckout(), refreshSessionOrders()])
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
  const current = pageContext(), previousCheckout = checkout.value?.id
  syncing.value = true
  error.value = ''
  try {
    const value = checkout.value
      ? await ticketApi.replaceCheckoutSessionSeats(checkout.value.id, next, checkout.value.revision)
      : next.length && session.value
        ? await ticketApi.createCheckoutSession(session.value.id, next)
        : null
    if (!current() || checkout.value?.id !== previousCheckout) return
    if (value) {
      checkout.value = value
      selectedSeatIds.value = [...value.seatIds]
      locatorWrite(value)
    }
    await refreshSeats()
  } catch (cause) {
    if (!current()) return
    if (isAdmissionFailure(cause)) return
    if (await handleSalesFailure(cause)) return
    if (!current()) return
    error.value = cause instanceof TicketApiError && [429,503].includes(cause.status??0) ? admissionErrorText(cause) : cause instanceof TicketApiError ? cause.message : '座位选择同步失败。'
    const isHoldConflict = cause instanceof TicketApiError && cause.code === 'SEAT_TEMPORARILY_HELD'
    let refreshed: boolean | undefined
    if (checkout.value) {
      try {
        const recovered = await readCheckout(checkout.value.id)
        if (recovered) refreshed = await activate(recovered)
      } catch { /* keep visible state */ }
    }
    if (isHoldConflict) {
      if (refreshed === undefined) refreshed = await refreshSeats()
      error.value = refreshed
        ? '所选座位刚被其他用户临时锁定，座位状态已刷新，请重新选择。'
        : '所选座位刚被其他用户临时锁定，最新座位状态暂未取得，请点击“刷新座位状态”后重试。'
    }
  } finally {
    if (current()) syncing.value = false
  }
}

async function clearSeats() {
  if (!checkout.value) return
  const current = pageContext(), id = checkout.value.id
  syncing.value = true
  try {
    const value = await ticketApi.replaceCheckoutSessionSeats(id, [], checkout.value.revision)
    if (!current() || checkout.value?.id !== id) return
    checkout.value = value
    selectedSeatIds.value = []
    locatorWrite(checkout.value)
    await refreshSeats()
  } finally {
    if (current()) syncing.value = false
  }
}

async function confirmCheckout() {
  if (!(await requireLogin()) || !checkout.value || !selectedSeatIds.value.length) return
  if (checkout.value.status === 'SELECTING' && !salesOpen.value) return
  const current = pageContext(), id = checkout.value.id
  confirming.value = true
  error.value = ''
  try {
    const result = await ticketApi.confirmCheckoutSession(id)
    if (!current() || checkout.value?.id !== id) return
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
    } else if (result.checkoutSession.status === 'SUBMITTING') startSubmittingPoll(id)
  } catch (cause) {
    if (!current() || checkout.value?.id !== id) return
    if (isAdmissionFailure(cause)) return
    if (await handleSalesFailure(cause)) return
    if (!current() || checkout.value?.id !== id) return
    error.value = cause instanceof TicketApiError && [429,503].includes(cause.status??0) ? admissionErrorText(cause) : cause instanceof TicketApiError ? cause.message : '确认结果暂时未知，正在恢复同一购票会话。'
    if (!(cause instanceof TicketApiError) || cause.status !== undefined && cause.status >= 500 || cause.code === 'INTERNAL_ERROR') startSubmittingPoll(checkout.value.id)
  } finally {
    if (current()) confirming.value = false
  }
}

function stopSubmitting() {
  pollingGeneration++
  clearTimeout(submittingTimer)
  submittingDeadline = 0
  submittingPolling.value = false
  submitUncertain.value = false
}
function finishSubmittingWindow() {
  clearTimeout(submittingTimer)
  submittingPolling.value = false
  submitUncertain.value = true
}
function scheduleSubmitting(id: string) {
  clearTimeout(submittingTimer)
  if (disposed || document.hidden || !submittingPolling.value || submittingWork || checkout.value?.id !== id) return
  const remaining = submittingDeadline - Date.now()
  if (remaining <= 0) { finishSubmittingWindow(); return }
  const delay = nextPollDelay({ emptyStreak: submittingEmpty, errorStreak: submittingErrors, retryAfterMs: submittingRetry }, Math.random, { baseMs: 2000, maxMs: 10000 })
  submittingTimer = setTimeout(() => {
    if (Date.now() >= submittingDeadline) finishSubmittingWindow()
    else void submittingTick(id)
  }, Math.min(delay, remaining))
}
async function submittingTick(id: string, finalAuthority = false): Promise<void> {
  const currentPage = pageContext(), generation = pollingGeneration, visible = submittingVisibility
  const current = () => currentPage() && generation === pollingGeneration && visible === submittingVisibility && checkout.value?.id === id
  if (submittingWork) {
    const pending = submittingWork
    if (pending.generation === generation && pending.visible === visible) return pending.promise
    await pending.promise
    if (current()) return submittingTick(id, finalAuthority)
    return
  }
  if (!current() || document.hidden || (!submittingPolling.value && !finalAuthority)) return
  if (!finalAuthority && Date.now() >= submittingDeadline) { finishSubmittingWindow(); return }
  clearTimeout(submittingTimer)
  const work = (async () => {
    try {
      const value = await readCheckout(id)
      if (!value || !current()) return
      checkout.value = value
      submittingErrors = 0; submittingRetry = undefined
      if (value.status !== 'SUBMITTING') {
        stopSubmitting()
        await activate(value)
        return
      }
      submittingEmpty = Math.min(6, submittingEmpty + 1)
      if (Date.now() >= submittingDeadline) finishSubmittingWindow()
    } catch (cause) {
      if (!current()) return
      submittingErrors = Math.min(5, submittingErrors + 1)
      submittingRetry = cause instanceof TicketApiError ? cause.retryAfterMs : undefined
      if (Date.now() >= submittingDeadline) finishSubmittingWindow()
    }
  })()
  submittingWork = { generation, visible, promise: work }
  try { await work } finally {
    if (submittingWork?.promise === work) submittingWork = undefined
    if (current()) scheduleSubmitting(id)
  }
}
function startSubmittingPoll(id: string) {
  pollingGeneration++
  clearTimeout(submittingTimer)
  submittingPolling.value = true
  submitUncertain.value = false
  submittingDeadline = Date.now() + 15000
  submittingEmpty = 0; submittingErrors = 0; submittingRetry = undefined
  void submittingTick(id)
}

async function abandon(value: CheckoutSession) {
  const current = pageContext()
  try {
    await ticketApi.abandonCheckoutSession(value.id)
    if (!current()) return
    recoverable.value = recoverable.value.filter((item) => item.id !== value.id)
    locatorClear()
    await refreshSeats()
  } catch (cause) {
    if (!current()) return
    error.value = cause instanceof TicketApiError ? cause.message : '放弃购票会话失败。'
  }
}

async function handleFocus() {
  if (identityPaused || disposed || document.hidden || Date.now() - lastFocusActivation < 500) return
  lastFocusActivation = Date.now()
  if (wasHidden || focusNeedsRead) { wasHidden=false; focusNeedsRead=false; requestForeground() }
  const currentPage = pageContext(), visible = submittingVisibility
  const current = () => currentPage() && visible === submittingVisibility && !document.hidden
  await focusReads.run(`${pageLoadEpoch}:${visible}`, async () => {
    await refreshSalesSession().catch(() => { /* Retain the last authoritative sales state. */ })
    if (!current()) return
    requestNotificationRefresh()
    await refreshSessionOrders().catch(() => { /* Explicit refresh can retry. */ })
    if (!current() || !checkout.value) return
    if (submittingDeadline || checkout.value.status === 'SUBMITTING') {
      await submittingTick(checkout.value.id, true)
    } else {
      try {
        const fresh = await readCheckout(checkout.value.id)
        if (current() && fresh && checkout.value && (fresh.revision !== checkout.value.revision || fresh.status !== checkout.value.status)) await activate(fresh)
      } catch { /* Keep the recoverable state visible. */ }
    }
  }, current)
}

onMounted(() => {
  void load()
  window.addEventListener('focus', handleFocus)
  window.addEventListener('blur', handleBlur)
  document.addEventListener('visibilitychange', visibilityChanged)
})
onBeforeUnmount(() => {
  disposed = true
  leasePolling?.stop()
  if (foregroundTimer !== undefined) clearTimeout(foregroundTimer)
  pageLoadEpoch++
  availabilityEpoch++
  stopAvailabilityTimer()
  document.removeEventListener('visibilitychange', visibilityChanged)
  stopSubmitting()
  window.removeEventListener('focus', handleFocus)
  window.removeEventListener('blur', handleBlur)
})
watch(() => authState.currentUser.value?.id, user => {
  stopSubmitting(); leasePolling?.stop()
  checkout.value = null; recoverable.value = []; selectedSeatIds.value = []; sessionOrders.value = []
  lastFocusActivation = -Infinity
  if (user) void load()
  else {
    identityPaused = true
    pageLoadEpoch++; availabilityEpoch++
    stopAvailabilityTimer()
    if (foregroundTimer !== undefined) clearTimeout(foregroundTimer)
    foregroundTimer = undefined
    loading.value = false
    error.value = '登录状态已结束，请重新登录后继续购票。'
    if (formalAdmission.value && session.value) void router.replace({ name: routeNames.login, query: { redirect: router.resolve(waitingTarget()).fullPath } })
  }
})
watch(() => route.params.sessionId, () => {
  stopSubmitting(); checkout.value = null; recoverable.value = []; selectedSeatIds.value = []; sessionOrders.value = []
  lastFocusActivation = -Infinity
  void load()
})
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
  <section v-if="admissionBlocked && session" class="selection-panel page-shell" aria-label="排队与已有购票恢复">
    <p>新的选座需要先完成排队，已有购票会话仍可恢复或释放。</p>
    <button class="primary-button" @click="enterWaitingRoom">前往排队</button>
    <template v-if="checkout">
      <button v-if="checkout.status==='SELECTING'" :disabled="syncing" @click="clearSeats">释放已选座位</button>
      <button v-if="checkout.status==='SELECTING'" :disabled="syncing" @click="abandon(checkout)">放弃此购票会话</button>
      <button v-if="checkout.status==='SUBMITTING'" :disabled="confirming" @click="confirmCheckout">恢复确认结果</button>
    </template>
    <RecoverableCheckoutPanel v-if="recoverable.length" :sessions="recoverable" :seats="seatLayout" @continue="activate" @abandon="abandon" @start-new="enterWaitingRoom" />
  </section>
  <SeatSelectionView
    v-if="event && session && seatMapLoaded && !admissionBlocked"
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
