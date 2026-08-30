import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SeatItem from './SeatItem.vue'
import type { Seat } from '../types'

const availableSeat: Seat = {
  id: 'seat-A01',
  sessionId: 'session-1',
  label: 'A01',
  row: 'A',
  number: 1,
  status: 'AVAILABLE',
  zone: '星光区',
  price: 1280,
}

describe('SeatItem', () => {
  it('emits toggle for an available seat', async () => {
    const wrapper = mount(SeatItem, {
      props: { seat: availableSeat, selected: false },
    })

    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('toggle')?.[0]).toEqual([availableSeat])
    wrapper.unmount()
  })

  it('disables held and sold seats', () => {
    const wrapper = mount(SeatItem, {
      props: {
        seat: { ...availableSeat, status: 'HELD' },
        selected: false,
      },
    })

    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button').attributes('aria-label')).toContain('锁定中')
    wrapper.unmount()
  })
})
