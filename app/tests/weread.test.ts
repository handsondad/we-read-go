import { describe, expect, it } from 'vitest'
import { GATEWAY, SKILL_VERSION, WereadClient, type GatewayRequest, type Transport } from '../src/core/weread'

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
  it('does not treat a required upgrade on optional progress as a warning', async () => {
    const { client, requests } = fixture((request) => ({
      status: 200, data: request.body.api_name === '/shelf/sync' ? { books: [rawBook] } : { upgrade_info: { version: 'next' } }
    }))
    await expect(client.sync()).rejects.toMatchObject({ fatal: true })
    expect(requests).toHaveLength(2)
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
  it.each([{}, { books: [null] }, { books: [rawBook, rawBook] }])('refuses malformed/duplicate shelf data', async (data) => {
    const { client } = fixture(() => ({ status: 200, data }))
    await expect(client.sync()).rejects.toThrow()
  })
  it('rejects invalid keys and gives actionable network errors without leaking Key', async () => {
    expect(() => new WereadClient('wrk-a\r\nBad', async () => ({ status: 200, data: {} }))).toThrow()
    const client = new WereadClient('wrk-example', async () => { throw new Error('sensitive transport details') })
    await expect(client.sync()).rejects.toThrow('CORS')
    await expect(client.sync()).rejects.not.toThrow('sensitive')
  })
})
