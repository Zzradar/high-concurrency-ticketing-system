const maxSafeFen = BigInt(Number.MAX_SAFE_INTEGER)
const invalidPrice = '票价须为至少 0.01 元的十进制金额，最多两位小数，且不能超出安全范围'

/** Keep the original decimal input until validation is complete. */
export function parseYuanPrice(value: string): number {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) throw new Error(invalidPrice)
  const [whole, fraction = ''] = value.split('.')
  const fen = BigInt(whole!) * 100n + BigInt(fraction.padEnd(2, '0'))
  if (fen <= 0n || fen > maxSafeFen) throw new Error(invalidPrice)
  return Number(fen)
}

export function formatFenPrice(fen: number): string {
  if (!Number.isSafeInteger(fen) || fen <= 0) throw new Error(invalidPrice)
  const exact = BigInt(fen)
  return `${exact / 100n}.${String(exact % 100n).padStart(2, '0')}`
}
