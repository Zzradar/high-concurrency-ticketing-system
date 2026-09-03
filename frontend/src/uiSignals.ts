export function showNotice(message: string) {
  window.dispatchEvent(new CustomEvent('ticketing:notice', { detail: message }))
}

export function requestNotificationRefresh() {
  window.dispatchEvent(new Event('ticketing:refresh-notifications'))
}
