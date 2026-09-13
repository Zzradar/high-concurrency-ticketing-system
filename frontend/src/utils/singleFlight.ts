// One in-flight read per owner. A new identity waits for the obsolete read to drain.
export class SingleFlight<T> {
  private pending: { key: string; promise: Promise<T | undefined> } | undefined

  async run(key: string, load: () => Promise<T>, isCurrent: () => boolean = () => true): Promise<T | undefined> {
    if (!isCurrent()) return undefined
    const pending = this.pending
    if (pending) {
      if (pending.key === key) {
        const value = await pending.promise
        return isCurrent() ? value : undefined
      }
      try { await pending.promise } catch { /* The original caller still receives its error. */ }
      return isCurrent() ? this.run(key, load, isCurrent) : undefined
    }
    const promise = Promise.resolve().then(() => isCurrent() ? load() : undefined)
    this.pending = { key, promise }
    try {
      const value = await promise
      return isCurrent() ? value : undefined
    } finally {
      if (this.pending?.promise === promise) this.pending = undefined
    }
  }
}
