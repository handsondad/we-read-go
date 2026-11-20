import { localDate, type Book } from './model'

export const GATEWAY = 'https://i.weread.qq.com/api/agent/gateway'
export const SKILL_VERSION = '1.0.3'

export interface GatewayRequest {
  url: string
  headers: Record<string, string>
  body: Record<string, unknown>
}

export type Transport = (request: GatewayRequest) => Promise<{ status: number; data: unknown }>

export class GatewayError extends Error {
  constructor(message: string, public readonly fatal = false) { super(message) }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function dateFromTimestamp(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  const date = new Date(value * 1000)
  return Number.isFinite(date.getTime()) ? localDate(date) : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export class WereadClient {
  constructor(private readonly apiKey: string, private readonly transport: Transport) {
    if (!/^wrk-[A-Za-z0-9_-]+$/.test(apiKey)) throw new Error('请输入完整的微信读书 API Key（wrk- 开头）')
  }

  private async call(apiName: string, params: Record<string, unknown> = {}) {
    let response: { status: number; data: unknown }
    try {
      response = await this.transport({
        url: GATEWAY,
        headers: { Authorization: `Bearer ${this.apiKey}`, 'Content-Type': 'application/json' },
        body: { ...params, api_name: apiName, skill_version: SKILL_VERSION }
      })
    } catch {
      throw new GatewayError('无法直连微信读书。请检查网络；浏览器预览可能受 CORS 限制，请在 App 真机重试。')
    }
    if (response.status === 401 || response.status === 403) {
      throw new GatewayError('API Key 无效或权限不足，请在微信读书官方页面重新获取。', true)
    }
    if (response.status < 200 || response.status >= 300) {
      throw new GatewayError(`微信读书服务暂不可用（HTTP ${response.status}），原书架不变。`)
    }
    if (!object(response.data)) throw new GatewayError('微信读书回包格式异常，原书架不变。')
    const data = response.data
    if (data.upgrade_info) {
      throw new GatewayError('微信读书要求升级 Skills 接口版本，请更新本应用后再同步。', true)
    }
    if (data.errcode !== undefined && data.errcode !== 0) {
      throw new GatewayError('微信读书拒绝了请求，请检查 Key、权限或接口版本后重试。', true)
    }
    return data
  }

  async sync(): Promise<{
    books: Book[]; readingSeconds: number | null; warnings: string[]
    albumCount: number; hasArticles: boolean
  }> {
    const shelf = await this.call('/shelf/sync')
    if (!Array.isArray(shelf.books)) throw new GatewayError('书架缺少 books 数组，原书架不变。')
    const books: Book[] = []
    const warnings: string[] = []
    for (const raw of shelf.books) {
      if (!object(raw) || !text(raw.bookId) || !text(raw.title).trim()) {
        throw new GatewayError('书架包含无效书目，原书架不变。')
      }
      const finished = raw.finishReading === 1
      let progress: number | null = finished ? 100 : null
      let lastReadAt = dateFromTimestamp(raw.readUpdateTime)
      if (!finished) {
        try {
          const result = await this.call('/book/getprogress', { bookId: raw.bookId })
          if (!object(result.book) || typeof result.book.progress !== 'number' ||
              !Number.isInteger(result.book.progress) || result.book.progress < 0 ||
              result.book.progress > 100) {
            throw new GatewayError('进度缺失或范围异常')
          }
          progress = result.book.progress
          lastReadAt = dateFromTimestamp(result.book.updateTime) ?? lastReadAt
        } catch (error) {
          if (!(error instanceof GatewayError) || error.fatal) throw error
          warnings.push(`《${text(raw.title)}》进度暂不可用，保留已有数据。`)
        }
      }
      books.push({
        id: `weread:${text(raw.bookId)}`, source: 'weread', title: text(raw.title),
        author: text(raw.author), cover: /^https:\/\//.test(text(raw.cover)) ? text(raw.cover) : '',
        status: finished || progress === 100 ? 'finished' : progress === 0 ? 'want' : 'reading',
        progress, lastReadAt, note: ''
      })
    }
    if (new Set(books.map((book) => book.id)).size !== books.length) {
      throw new GatewayError('微信读书返回重复书目，原书架不变。')
    }
    let readingSeconds: number | null = null
    try {
      const stats = await this.call('/readdata/detail', { mode: 'overall' })
      if (typeof stats.totalReadTime !== 'number' || !Number.isFinite(stats.totalReadTime) ||
          stats.totalReadTime < 0) throw new GatewayError('缺少阅读时长')
      readingSeconds = stats.totalReadTime
    } catch (error) {
      if (!(error instanceof GatewayError) || error.fatal) throw error
      warnings.push('累计阅读时长暂不可用，保留上次数据。')
    }
    return {
      books, readingSeconds, warnings,
      albumCount: Array.isArray(shelf.albums) ? shelf.albums.length : 0,
      hasArticles: object(shelf.mp) && Object.keys(shelf.mp).length > 0
    }
  }
}
