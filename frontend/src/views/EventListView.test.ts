import { mount, enableAutoUnmount } from '@vue/test-utils'
import { afterEach, expect, it } from 'vitest'
import EventListView from './EventListView.vue'
import { ticketApi, setMockLatency } from '../api/ticketApi'
enableAutoUnmount(afterEach)
it('keeps loading, empty, one, many and reloaded counts in sync with the cards', async () => {
  setMockLatency(0)
  const events = await ticketApi.getEvents()
  const wrapper = mount(EventListView, { props: { events: [], loading: true }, global: { stubs: { RouterLink: true } } })
  expect(wrapper.text()).toContain('正在加载活动')
  for (const list of [[], events.slice(0, 1), events, []]) {
    await wrapper.setProps({ events: list, loading: false })
    expect(wrapper.text()).toContain(list.length ? `共 ${list.length} 场活动可浏览` : '暂无可浏览活动')
    expect(wrapper.findAll('.event-card')).toHaveLength(list.length)
    expect(wrapper.text()).not.toContain('2 场活动正在售票')
    await wrapper.setProps({ loading: true })
    expect(wrapper.text()).toContain('正在加载活动')
  }
})
