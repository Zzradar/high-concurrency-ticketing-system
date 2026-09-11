import { summarizeSeatZones } from '../utils/seatMap'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SeatSelectionView from './SeatSelectionView.vue'
import type { Seat, TicketEvent, TicketSession } from '../types'

const event: TicketEvent = {
  id: 'event-1', name: '测试活动', description: '说明', city: '上海', venue: '测试馆',
  dateRange: '2026.10.01', status: 'ON_SALE', cover: '/cover.png', sessionCount: 1, category: '演唱会',
}
const session: TicketSession = {
  id: 'session-1', eventId: event.id, date: '10月01日', time: '19:30', weekday: '周四',
  venue: '测试馆', gateTime: '18:00', status: 'ON_SALE', priceFrom: 58000, availability: '充足',
}
const seats: Seat[] = [
  { id: 'A1', sessionId: session.id, label: 'A01', row: 'A', number: 1, zone: '星光区', price: 128000, status: 'AVAILABLE' },
  { id: 'A2', sessionId: session.id, label: 'A02', row: 'A', number: 2, zone: '星光区', price: 128000, status: 'HELD' },
  { id: 'B1', sessionId: session.id, label: 'B01', row: 'B', number: 1, zone: '看台 A 区', price: 88000, status: 'AVAILABLE' },
  { id: 'B2', sessionId: session.id, label: 'B02', row: 'B', number: 2, zone: '看台 A 区', price: 88000, status: 'SOLD' },
]

function mountView(overrides: Record<string, unknown> = {}) {
  return mount(SeatSelectionView, {
    props: {
      event,
      session,
      seats: seats.filter(s => s.zone === seats[0]!.zone),
      seatLayout: seats,
      activeZone: seats[0]!.zone,
      zoneSummaries: summarizeSeatZones(seats),
      selectedSeats: [seats[0]!, seats[2]!],
      selectedSeatIds: ['A1', 'B1'],
      checkoutSession: null,
      recoverableCheckoutSessions: [],
      loading: false,
      refreshing: false,
      availabilityWarning: '',
      checkoutCreating: false,
      checkoutSyncInFlight: false,
      confirming: false,
      submittingPolling: false,
      submitUncertain: false,
      editingDisabled: false,
      ...overrides,
    },
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('SeatSelectionView zone browsing', () => {
  it('derives zone tabs and session status counts from the seat snapshot', () => {
    const wrapper = mountView()
    expect(wrapper.find('.seat-status-summary').text()).toContain('可选2')
    expect(wrapper.find('.seat-status-summary').text()).toContain('锁定中1')
    expect(wrapper.find('.seat-status-summary').text()).toContain('已售1')
    expect(wrapper.find('.seat-status-summary').text()).toContain('已选2 / 6')
    expect(wrapper.findAll('.zone-browser button').map((button) => button.text())).toEqual([
      '星光区可选 1 · 共 2',
      '看台 A 区可选 1 · 共 2',
    ])
  })

  it('renders only the active zone while preserving cross-zone selection', async () => {
    const wrapper = mountView()
    const seatGrid = wrapper.get<HTMLElement>('.seat-grid')
    seatGrid.element.scrollLeft = 280
    const standZone = wrapper.findAll('.zone-browser button').find((button) => button.text().includes('看台 A 区'))!
    await standZone.trigger('click')
    expect(wrapper.emitted('changeZone')).toEqual([['看台 A 区']])
    await wrapper.setProps({activeZone:'看台 A 区',seats:seats.filter(s => s.zone === '看台 A 区')})

    expect(seatGrid.element.scrollLeft).toBe(0)
    expect(wrapper.findAll('.seat-item')).toHaveLength(2)
    expect(wrapper.find('.seat-map-panel__heading').text()).toContain('看台 A 区')
    expect(wrapper.findAll('.selected-seat').map((seat) => seat.text()).join(' ')).toContain('A01')
    expect(wrapper.findAll('.selected-seat').map((seat) => seat.text()).join(' ')).toContain('B01')
  })

  it('shows refresh and editing-disabled feedback without clearing the snapshot', () => {
    const wrapper = mountView({
      refreshing: true,
      editingDisabled: true,
      availabilityWarning: '座位状态暂未刷新，请稍后重试。',
    })
    expect(wrapper.findAll('.seat-item')).toHaveLength(2)
    expect(wrapper.text()).toContain('已保留当前座位图')
    expect(wrapper.get('.seat-map-panel').classes()).toContain('is-editing-disabled')
    expect(wrapper.get('button[aria-label="正在刷新座位状态"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button[aria-label="正在刷新座位状态"]').attributes('aria-busy')).toBe('true')
    expect(wrapper.get('button[aria-label="正在刷新座位状态"]').text()).toBe('正在刷新')
  })

  it('exposes a visible refresh action and prevents another click while refreshing', async () => {
    const wrapper = mountView()
    const button = wrapper.get('button[aria-label="刷新座位状态"]')
    expect(button.text()).toBe('刷新座位状态')
    expect(button.attributes('aria-busy')).toBe('false')
    await button.trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    await wrapper.setProps({ refreshing: true })
    await button.trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    wrapper.unmount()
  })
})
