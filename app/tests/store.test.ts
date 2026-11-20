import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialData } from '../src/core/model'
import { DATA_KEY } from '../src/core/storage'
import type { Transport } from '../src/core/weread'

const mocks = vi.hoisted(() => ({
  values: new Map<string, unknown>(),
  write: vi.fn<(key: string, value: string) => void>(),
  transport: vi.fn<Transport>(),
  notifyError: vi.fn(),
  modal: vi.fn()
}))
vi.mock('../src/platform', () => ({
  storage: {
    get: (key: string) => mocks.values.get(key),
    set: (key: string, value: string) => mocks.write(key, value)
  },
  transport: mocks.transport,
  notifyError: mocks.notifyError
}))

let store: typeof import('../src/store')
beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 8, 24, 21, 0))
  mocks.values.clear()
  mocks.write.mockReset().mockImplementation((key, value) => { mocks.values.set(key, value) })
  mocks.transport.mockReset()
  mocks.notifyError.mockReset()
  mocks.modal.mockReset()
  vi.stubGlobal('uni', { showModal: mocks.modal })
  store = await import('../src/store')
})
afterEach(() => {
  store.pause()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('application lifecycle and local-first state', () => {
  it('creates local books/notes/reading records offline and reloads them', async () => {
    store.initialize()
    store.addBook('My book', 'Author', 'want')
    const id = store.state.data.books[0].id
    store.updateBook(id, 'reading', 'A thought')
    store.readToday(id)
    expect(store.todayDone.value).toBe(true)
    expect(mocks.transport).not.toHaveBeenCalled()
    vi.resetModules()
    const reloaded = await import('../src/store')
    reloaded.initialize()
    expect(reloaded.state.data).toEqual(store.state.data)
    expect(reloaded.state.data.books[0].note).toBe('A thought')
    expect(reloaded.state.connected).toBe(false)
  })
  it('blocks writes on corrupt storage and restores only explicitly validated backup data', () => {
    mocks.values.set(DATA_KEY, '{broken')
    store.initialize()
    expect(store.state.storageError).not.toBe('')
    expect(mocks.notifyError).toHaveBeenCalledOnce()
    expect(() => store.addBook('Book', '', 'want')).toThrow()
    expect(() => store.exportBackup()).toThrow()
    expect(() => store.restoreBackup('bad')).toThrow()
    expect(mocks.write).not.toHaveBeenCalled()
    store.restoreBackup(JSON.stringify(initialData()))
    expect(store.state.storageError).toBe('')
    store.addBook('Recovered', '', 'want')
    expect(store.state.data.books[0].title).toBe('Recovered')
  })
  it('does not mutate reactive state on disk errors', () => {
    store.initialize()
    mocks.write.mockImplementation(() => { throw new Error('disk full') })
    expect(() => store.addBook('Book', '', 'want')).toThrow('disk full')
    expect(store.state.data.books).toHaveLength(0)
    expect(() => store.restoreBackup(JSON.stringify(initialData()))).toThrow('disk full')
  })
  it('never persists or exports the Key and clears it on disconnect', async () => {
    store.initialize()
    store.connect('wrk-example')
    store.addBook('Book', '', 'want')
    expect(String(mocks.values.get(DATA_KEY))).not.toContain('wrk-example')
    expect(store.exportBackup()).not.toContain('wrk-example')
    store.disconnect()
    await expect(store.syncReading()).rejects.toThrow('Key')
    expect(mocks.transport).not.toHaveBeenCalled()
  })
  it('does not update shelf or sync timestamp when authentication fails partway', async () => {
    store.initialize()
    store.addBook('Local', '', 'want')
    store.connect('wrk-example')
    mocks.transport.mockImplementation(async (request) => request.body.api_name === '/shelf/sync'
      ? { status: 200, data: { books: [{ bookId: 'one', title: 'Remote' }] } }
      : { status: 401, data: {} })
    const previous = store.exportBackup()
    await expect(store.syncReading()).rejects.toThrow()
    expect(store.exportBackup()).toBe(previous)
    expect(store.state.busy).toBe(false)
    expect(store.state.syncMessage).toContain('Key')
    // A rejected Key is dropped from memory, so the UI no longer claims it is set.
    expect(store.state.connected).toBe(false)
    mocks.transport.mockClear()
    await expect(store.syncReading()).rejects.toThrow('Key')
    expect(mocks.transport).not.toHaveBeenCalled()
  })
  it('keeps the Key after a temporary failure', async () => {
    store.initialize()
    store.connect('wrk-example')
    mocks.transport.mockResolvedValue({ status: 503, data: {} })
    await expect(store.syncReading()).rejects.toThrow()
    expect(store.state.connected).toBe(true)
  })
  it('asks progress only for books read since the previous sync and keeps local edits to the rest', async () => {
    store.initialize()
    store.connect('wrk-example')
    let stamp = 1720000000
    const messages: string[] = []
    mocks.transport.mockImplementation(async (request) => {
      if (request.body.api_name === '/book/getprogress') messages.push(store.state.syncMessage)
      return {
        status: 200, data: request.body.api_name === '/shelf/sync' ? { books: [
          { bookId: 'one', title: 'Remote', readUpdateTime: stamp },
          { bookId: 'two', title: 'Other', readUpdateTime: 1700000000 }
        ] } : request.body.api_name === '/book/getprogress'
          ? { book: { progress: request.body.bookId === 'one' ? 40 : 10 } } : { totalReadTime: 30 }
      }
    })
    await store.syncReading()
    expect(mocks.transport).toHaveBeenCalledTimes(4)
    expect(messages[0]).toContain('0 / 2')
    store.updateBook('weread:two', 'want', 'my note')

    mocks.transport.mockClear()
    stamp = 1720009999
    await store.syncReading()
    const asked = mocks.transport.mock.calls.map(([request]) => request.body)
      .filter((body) => body.api_name === '/book/getprogress').map((body) => body.bookId)
    expect(asked).toEqual(['one'])
    expect(store.state.data.books.find((book) => book.id === 'weread:two')).toMatchObject({
      status: 'want', progress: 10, note: 'my note', syncedReadTime: 1700000000
    })
    expect(store.state.data.books.find((book) => book.id === 'weread:one')).toMatchObject({
      progress: 40, syncedReadTime: 1720009999
    })
    expect(store.state.syncMessage).toContain('1 本最近阅读时间没有变化')
  })
  it('allows a single sync and merges against local changes made while waiting', async () => {
    store.initialize()
    store.connect('wrk-example')
    let resolveShelf!: (response: { status: number; data: unknown }) => void
    mocks.transport.mockImplementation((request) => request.body.api_name === '/shelf/sync'
      ? new Promise((resolve) => { resolveShelf = resolve })
      : Promise.resolve({ status: 200, data: { totalReadTime: 30 } }))
    const syncing = store.syncReading()
    expect(store.state.busy).toBe(true)
    await store.syncReading()
    expect(mocks.transport).toHaveBeenCalledOnce()
    expect(() => store.disconnect()).toThrow()
    expect(() => store.connect('wrk-new')).toThrow()
    expect(() => store.restoreBackup(JSON.stringify(initialData()))).toThrow()
    store.addBook('Added while syncing', '', 'want')
    resolveShelf({ status: 200, data: { books: [{ bookId: 'one', title: 'Remote', finishReading: 1 }] } })
    await syncing
    expect(store.state.data.books).toHaveLength(2)
    expect(store.state.data.readingSeconds).toBe(30)
    expect(store.state.data.lastSyncAt).not.toBeNull()
    expect(store.state.busy).toBe(false)
  })
  it('retains the last good official progress, status, date, and total on optional errors', async () => {
    const data = initialData()
    data.readingSeconds = 600
    data.books = [{
      id: 'weread:one', source: 'weread', title: 'Remote', author: '', cover: '',
      status: 'reading', progress: 40, lastReadAt: '2026-09-20', note: 'keep', syncedReadTime: null
    }]
    mocks.values.set(DATA_KEY, JSON.stringify(data))
    store.initialize()
    store.connect('wrk-example')
    mocks.transport.mockImplementation(async (request) => request.body.api_name === '/shelf/sync'
      ? { status: 200, data: { books: [{ bookId: 'one', title: 'Remote' }] } }
      : { status: 503, data: {} })
    await store.syncReading()
    expect(store.state.data.books[0]).toMatchObject({
      status: 'reading', progress: 40, lastReadAt: '2026-09-20', note: 'keep'
    })
    expect(store.state.data.readingSeconds).toBe(600)
    expect(store.state.syncMessage).toContain('暂不可用')
    expect(store.state.data.lastSyncAt).not.toBeNull()
  })
  it('checks foreground reminders once daily and pauses the timer when hidden', () => {
    store.initialize()
    store.setReminder(true, '21:00')
    store.resume()
    expect(mocks.modal).toHaveBeenCalledOnce()
    vi.advanceTimersByTime(60000)
    expect(mocks.modal).toHaveBeenCalledOnce()
    store.pause()
    expect(vi.getTimerCount()).toBe(0)
    store.resume()
    expect(mocks.modal).toHaveBeenCalledOnce()
    store.pause()
    vi.setSystemTime(new Date(2026, 8, 25, 21, 0))
    store.readToday(null)
    store.resume()
    expect(mocks.modal).toHaveBeenCalledOnce()
  })
  it('reports a failed reminder write once instead of on every timer tick', () => {
    store.initialize()
    store.setReminder(true, '21:00')
    mocks.write.mockImplementation(() => { throw new Error('disk full') })
    store.resume()
    vi.advanceTimersByTime(120000)
    expect(mocks.notifyError).toHaveBeenCalledOnce()
    expect(mocks.modal).not.toHaveBeenCalled()
  })
})
