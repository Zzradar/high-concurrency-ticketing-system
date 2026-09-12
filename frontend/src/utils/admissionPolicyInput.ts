export function admissionInteger(raw: unknown, min: number, max: number): number {
 if (typeof raw !== 'string' || !/^(0|[1-9][0-9]*)$/.test(raw)) throw new Error('准入策略只接受不含空白的十进制整数')
 const value = Number(raw)
 if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`准入策略数值必须在 ${min} 至 ${max} 之间`)
 return value
}
