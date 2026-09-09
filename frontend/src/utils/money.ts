const cnyFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

/**
 * API 金额统一使用整数“分”，页面按人民币“元”展示。
 */
export function formatCny(amountInFen: number): string {
  if (!Number.isFinite(amountInFen)) return '¥0'
  return '¥' + cnyFormatter.format(amountInFen / 100)
}

/** Refund.currency is the immutable server currency, not the deployment default. */
export function formatMoney(amount: number, currency: string): string {
  if (currency.toLowerCase() === 'cny') return formatCny(amount)
  const formatter = new Intl.NumberFormat('zh-CN', { style: 'currency', currency })
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2
  return formatter.format(amount / 10 ** digits)
}
