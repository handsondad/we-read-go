import { describe, expect, it } from 'vitest'
import type { Book } from '../src/core/model'
import {
  GATEWAY, PROGRESS_CONCURRENCY, SKILL_VERSION, WereadClient, type GatewayRequest, type Transport
} from '../src/core/weread'

const rawBook = { bookId: 'one', title: 'A book', author: 'Author', cover: 'http://insecure', finishReading: 0 }
function fixture(handler: (request: GatewayRequest) => { status: number; data: unknown }) {
  const requests: GatewayRequest[] = []
  const transport: Transport = async (request) => { requests.push(request); return handler(request) }
  return { requests, client: new WereadClient('wrk-example', transport) }
}
describe('official gateway contract', () => {
  it.each([0, 1, 100])('keeps %i percent as a percentage and sends flattened parameters', async (progress) => {
    const { client, requests } = fixture((request) => ({
      status: 200, data: request.body.api_name === '/shelf/sync' ? { books: [rawBook] }
        : request.body.api_name === '/book/getprogress' ? { book: { progress, updateTime: 1720000000 } }
        : { totalReadTime: 3661 }
    }))
    const result = await client.sync()
    expect(result.books[0].progress).toBe(progress)
    expect(result.books[0].status).toBe(progress === 0 ? 'want' : progress === 100 ? 'finished' : 'reading')
    expect(result.books[0].cover).toBe('')
    expect(result.readingSeconds).toBe(3661)
    expect(result.warnings).toEqual([])
    expect(requests[0].url).toBe(GATEWAY)
    expect(requests[0].headers.Authorization).toBe('Bearer wrk-example')
    expect(requests[1].body).toEqual({
      api_name: '/book/getprogress', skill_version: SKILL_VERSION, bookId: 'one'
    })
    expect(requests[2].body.mode).toBe('overall')
    expect(requests.every((request) => !('params' in request.body))).toBe(true)
  })
  it('uses finished status directly and reports unsupported shelf categories', async () => {
    const { client, requests } = fixture(() => ({
      status: 200, data: { books: [{ ...rawBook, finishReading: 1 }], albums: [{}], mp: { id: 1 }, totalReadTime: 0 }
    }))
    const result = await client.sync()
    expect(result.books[0].progress).toBe(100)
    expect(result.albumCount).toBe(1)
    expect(result.hasArticles).toBe(true)
    expect(requests).toHaveLength(2)
  })
  it.each([401, 403])('stops immediately on HTTP %i', async (status) => {
    const { client, requests } = fixture(() => ({ status, data: {} }))
    await expect(client.sync()).rejects.toMatchObject({ fatal: true })
    expect(requests).toHaveLength(1)
  })
  it('treats upgrade_info as a non-blocking notice and still uses the data beside it', async () => {
    const upgrade_info = { version: 'next' }
    const { client, requests } = fixture((request) => ({
      status: 200, data: request.body.api_name === '/shelf/sync' ? { books: [rawBook], upgrade_info }
        : request.body.api_name === '/book/getprogress' ? { book: { progress: 37 }, upgrade_info }
        : { totalReadTime: 60, upgrade_info }
    }))
    const result = await client.sync()
    expect(result.books[0].progress).toBe(37)
    expect(result.readingSeconds).toBe(60)
    expect(result.warnings).toHaveLength(1)
    expect(result.warnings[0]).toContain('版本')
    expect(requests).toHaveLength(3)
  })
  it('stops when an upgrade notice arrives without any shelf data', async () => {
    const { client, requests } = fixture(() => ({ status: 200, data: { upgrade_info: { version: 'next' } } }))
    await expect(client.sync()).rejects.toMatchObject({ fatal: true })
    expect(requests).toHaveLength(1)
  })
  it('reports optional failures with nulls, never fabricated zero progress', async () => {
    const { client } = fixture((request) => request.body.api_name === '/shelf/sync'
      ? { status: 200, data: { books: [rawBook] } } : { status: 503, data: {} })
    const result = await client.sync()
    expect(result.books[0].progress).toBeNull()
    expect(result.readingSeconds).toBeNull()
    expect(result.warnings).toHaveLength(2)
  })
  it.each([-1, 101, 0.5, '20', null])('does not import invalid progress %s', async (progress) => {
    const { client } = fixture((request) => ({
      status: 200, data: request.body.api_name === '/shelf/sync' ? { books: [rawBook] }
        : request.body.api_name === '/book/getprogress' ? { book: { progress } } : { totalReadTime: 1 }
    }))
    const result = await client.sync()
    expect(result.books[0].progress).toBeNull()
    expect(result.warnings).toHaveLength(1)
  })
  it.each([{}, { books: [null] }, { books: [rawBook, rawBook] }, { books: [rawBook, { bookId: 'two' }] }])(
    'refuses malformed/duplicate shelf data before asking for any progress', async (data) => {
      const { client, requests } = fixture(() => ({ status: 200, data }))
      await expect(client.sync()).rejects.toThrow()
      expect(requests).toHaveLength(1)
    })
  it('queries progress with bounded concurrency and keeps shelf order', async () => {
    const shelf = Array.from({ length: 10 }, (_, index) => ({ bookId: `b${index}`, title: `Book ${index}` }))
    let running = 0
    let peak = 0
    const calls: Array<[number, number]> = []
    const transport: Transport = async (request) => {
      if (request.body.api_name === '/shelf/sync') return { status: 200, data: { books: shelf } }
      if (request.body.api_name === '/readdata/detail') return { status: 200, data: { totalReadTime: 1 } }
      peak = Math.max(peak, ++running)
      const index = Number(String(request.body.bookId).slice(1))
      // Earlier books answer later, so order must come from the shelf, not from arrival time.
      await new Promise((resolve) => setTimeout(resolve, (10 - index) * 3))
      running--
      return { status: 200, data: { book: { progress: index + 1 } } }
    }
    const result = await new WereadClient('wrk-example', transport).sync({
      onProgress: (done, total) => calls.push([done, total])
    })
    expect(peak).toBe(PROGRESS_CONCURRENCY)
    expect(result.books.map((book) => book.progress)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    expect(calls[0]).toEqual([0, 10])
    expect(calls.at(-1)).toEqual([10, 10])
    expect(calls).toHaveLength(11)
  })
  it('starts no further progress requests after a fatal answer', async () => {
    const shelf = Array.from({ length: 12 }, (_, index) => ({ bookId: `b${index}`, title: `Book ${index}` }))
    const { client, requests } = fixture((request) => request.body.api_name === '/shelf/sync'
      ? { status: 200, data: { books: shelf } } : { status: 401, data: {} })
    await expect(client.sync()).rejects.toMatchObject({ fatal: true, authFailed: true })
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(requests.length).toBeLessThanOrEqual(1 + PROGRESS_CONCURRENCY)
  })
  it('skips progress for books whose last read time is unchanged, and refetches the rest', async () => {
    const known = (fields: Partial<Book>): Book => ({
      id: 'weread:same', source: 'weread', title: 'Old title', author: '', cover: '', status: 'reading',
      progress: 40, lastReadAt: '2024-07-03', note: '', syncedReadTime: 1720000000, ...fields
    })
    const { client, requests } = fixture((request) => ({
      status: 200, data: request.body.api_name === '/shelf/sync' ? { books: [
        { bookId: 'same', title: 'Same', readUpdateTime: 1720000000 },
        { bookId: 'moved', title: 'Moved', readUpdateTime: 1720009999 },
        { bookId: 'unknown', title: 'Unknown progress', readUpdateTime: 1720000000 },
        { bookId: 'nostamp', title: 'No stamp' },
        { bookId: 'new', title: 'New', readUpdateTime: 1720000000 }
      ] } : request.body.api_name === '/book/getprogress' ? { book: { progress: 55 } } : { totalReadTime: 1 }
    }))
    const calls: Array<[number, number]> = []
    const result = await client.sync({
      previous: [
        known({}), known({ id: 'weread:moved' }), known({ id: 'weread:unknown', progress: null }),
        known({ id: 'weread:nostamp', syncedReadTime: null })
      ],
      onProgress: (done, total) => calls.push([done, total])
    })
    const asked = requests.filter((request) => request.body.api_name === '/book/getprogress')
      .map((request) => request.body.bookId)
    expect(asked.sort()).toEqual(['moved', 'new', 'nostamp', 'unknown'])
    expect(result.unchanged).toBe(1)
    expect(result.warnings).toEqual([])
    expect(result.books[0]).toMatchObject({ title: 'Same', progress: null, syncedReadTime: 1720000000 })
    expect(result.books[1]).toMatchObject({ progress: 55, syncedReadTime: 1720009999 })
    expect(result.books[3]).toMatchObject({ progress: 55, syncedReadTime: null })
    expect(calls[0]).toEqual([0, 4])
  })
  it('does not record a read stamp when progress fails, and summarises many failures', async () => {
    const shelf = Array.from({ length: 5 }, (_, index) => ({
      bookId: `b${index}`, title: `Book ${index}`, readUpdateTime: 1720000000
    }))
    const { client } = fixture((request) => request.body.api_name === '/shelf/sync'
      ? { status: 200, data: { books: shelf } } : { status: 503, data: {} })
    const result = await client.sync()
    expect(result.books.every((book) => book.progress === null && book.syncedReadTime === null)).toBe(true)
    expect(result.warnings).toHaveLength(2)
    expect(result.warnings[0]).toContain('5 本')
  })
  it('rejects invalid keys and gives actionable network errors without leaking Key', async () => {
    expect(() => new WereadClient('wrk-a\r\nBad', async () => ({ status: 200, data: {} }))).toThrow()
    const client = new WereadClient('wrk-example', async () => { throw new Error('sensitive transport details') })
    await expect(client.sync()).rejects.toThrow('CORS')
    await expect(client.sync()).rejects.not.toThrow('sensitive')
  })
})
