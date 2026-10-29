import { describe, expect, it } from 'vitest'
import { initialData } from '../src/core/model'
import { DATA_KEY, loadData, parseData, saveData, type StoragePort } from '../src/core/storage'

describe('local data persistence', () => {
  it('starts empty only when no stored value exists', () => {
    expect(loadData({ get: () => '', set: () => {} })).toEqual(initialData())
    expect(() => loadData({ get: () => 123, set: () => {} })).toThrow()
  })
  it('round-trips an allow-listed shape without credentials or unexpected fields', () => {
    const data = { ...initialData(), apiKey: 'not-a-real-key', unexpected: true }
    let raw = ''
    const port: StoragePort = {
      get: (key) => { expect(key).toBe(DATA_KEY); return raw },
      set: (key, value) => { expect(key).toBe(DATA_KEY); raw = value }
    }
    saveData(port, data)
    expect(raw).not.toContain('apiKey')
    expect(raw).not.toContain('unexpected')
    expect(loadData(port)).toEqual(initialData())
  })
  it.each([
    '{broken', JSON.stringify({ ...initialData(), version: 2 }),
    JSON.stringify({ ...initialData(), reminder: { enabled: true, time: '25:30', lastShownOn: null } }),
    JSON.stringify({ ...initialData(), entries: [{ date: '2026-02-30', bookId: null }] }),
    JSON.stringify({ ...initialData(), entries: [
      { date: '2026-09-24', bookId: null }, { date: '2026-09-24', bookId: null }
    ] }),
    JSON.stringify({ ...initialData(), readingSeconds: -1 })
  ])('refuses corrupt and unsupported data without writing over it', (raw) => {
    let writes = 0
    expect(() => loadData({ get: () => raw, set: () => { writes++ } })).toThrow()
    expect(writes).toBe(0)
  })
  it('surfaces storage write failures instead of claiming success', () => {
    expect(() => saveData({
      get: () => '', set: () => { throw new Error('disk full') }
    }, initialData())).toThrow('disk full')
  })
  it('strips nested unknown fields when importing backups', () => {
    const raw = JSON.stringify({
      ...initialData(),
      reminder: { ...initialData().reminder, apiKey: 'not-a-real-key' },
      entries: [{ date: '2026-09-24', bookId: null, secret: 'unused' }]
    })
    expect(JSON.stringify(parseData(raw))).not.toContain('not-a-real-key')
    expect(JSON.stringify(parseData(raw))).not.toContain('secret')
  })
  it('rejects invalid book states and non-HTTPS imported covers', () => {
    const book = {
      id: 'manual:one', source: 'manual', title: 'Book', author: '', cover: '',
      status: 'want', progress: null, lastReadAt: null, note: ''
    }
    for (const invalid of [{ ...book, status: ['want'] }, { ...book, cover: 'http://insecure' }]) {
      expect(() => parseData(JSON.stringify({ ...initialData(), books: [invalid] }))).toThrow()
    }
  })
})
