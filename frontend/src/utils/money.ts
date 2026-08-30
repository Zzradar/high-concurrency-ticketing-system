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
