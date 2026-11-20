import { localDate, type Book } from './model'

export const GATEWAY = 'https://i.weread.qq.com/api/agent/gateway'
// 与官方 Skill（github.com/Tencent/WeChatReading）的 version 保持一致；本文件用到的三个接口按该版本文档核对。
export const SKILL_VERSION = '1.0.6'
/** 同时进行的进度查询数量上限，避免几百本书一拥而上。 */
export const PROGRESS_CONCURRENCY = 4

export interface GatewayRequest {
  url: string
  headers: Record<string, string>
  body: Record<string, unknown>
}

export type Transport = (request: GatewayRequest) => Promise<{ status: number; data: unknown }>

export class GatewayError extends Error {
  constructor(
    message: string,
    /** 致命错误：中止本次同步，不写入半份结果。 */
    public readonly fatal = false,
    /** 凭证被拒绝（HTTP 401/403）：这个 Key 不能再用。 */
    public readonly authFailed = false
  ) { super(message) }
}

export interface SyncOptions {
  /** 本机已有书目。最近阅读时间未变且进度已知的书，不再逐本查询。 */
  previous?: readonly Book[]
  /** 进度查询每完成一本回调一次；total 为本次真正需要查询的本数。 */
  onProgress?: (done: number, total: number) => void
}

export interface SyncResult {
  /** progress 为 null 表示这次没有新的进度信息（查询失败或跳过），由 mergeShelf 保留本机数据。 */
  books: Book[]
  readingSeconds: number | null
  warnings: string[]
  albumCount: number
  hasArticles: boolean
  /** 因最近阅读时间未变而跳过进度查询的本数。 */
  unchanged: number
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function dateFromTimestamp(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  const date = new Date(value * 1000)
  return Number.isFinite(date.getTime()) ? localDate(date) : null
}

function readStamp(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function assertApiKey(apiKey: string): void {
  if (!/^wrk-[A-Za-z0-9_-]+$/.test(apiKey)) throw new Error('请输入完整的微信读书 API Key（wrk- 开头）')
}

/** 按原顺序返回结果，同时最多执行 limit 个任务；任一任务抛错后不再启动新任务。 */
async function mapLimit<T, R>(
  items: readonly T[], limit: number, task: (item: T) => Promise<R>
): Promise<R[]> {
  const results = new Array<R>(items.length)
  let next = 0
  let failed = false
  const worker = async () => {
    while (!failed && next < items.length) {
      const index = next++
      try {
        results[index] = await task(items[index])
      } catch (error) {
        failed = true
        throw error
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}

export class WereadClient {
  constructor(private readonly apiKey: string, private readonly transport: Transport) {
    assertApiKey(apiKey)
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
      throw new GatewayError('API Key 无效或权限不足，请在微信读书官方页面重新获取。', true, true)
    }
    if (response.status < 200 || response.status >= 300) {
      throw new GatewayError(`微信读书服务暂不可用（HTTP ${response.status}），原书架不变。`)
    }
    if (!object(response.data)) throw new GatewayError('微信读书回包格式异常，原书架不变。')
    const data = response.data
    if (data.errcode !== undefined && data.errcode !== 0) {
      throw new GatewayError('微信读书拒绝了请求，请检查 Key、权限或接口版本后重试。', true)
    }
    // upgrade_info 按官方约定只是非阻塞的升级通知，同一回包里的业务数据照常使用，由 sync 汇总成提示。
    return data
  }

  async sync(options: SyncOptions = {}): Promise<SyncResult> {
    const shelf = await this.call('/shelf/sync')
    let upgradeNotice = Boolean(shelf.upgrade_info)
    if (!Array.isArray(shelf.books)) {
      throw new GatewayError(upgradeNotice
        ? '微信读书提示接口版本有更新，且没有返回书架数据；请更新本应用后再同步。原书架不变。'
        : '书架缺少 books 数组，原书架不变。', upgradeNotice)
    }

    // 先把整份书架校验完，再发逐本请求：数据有问题时不白白发出几百个请求。
    const previous = new Map((options.previous ?? []).map((book) => [book.id, book]))
    const ids = new Set<string>()
    const drafts = shelf.books.map((raw) => {
      if (!object(raw) || !text(raw.bookId) || !text(raw.title).trim()) {
        throw new GatewayError('书架包含无效书目，原书架不变。')
      }
      const id = `weread:${text(raw.bookId)}`
      if (ids.has(id)) throw new GatewayError('微信读书返回重复书目，原书架不变。')
      ids.add(id)
      const finished = raw.finishReading === 1
      const stamp = readStamp(raw.readUpdateTime)
      const old = previous.get(id)
      const unchanged = !finished && stamp !== null && old !== undefined &&
        old.progress !== null && old.syncedReadTime === stamp
      return {
        id, bookId: text(raw.bookId), title: text(raw.title), author: text(raw.author),
        cover: /^https:\/\//.test(text(raw.cover)) ? text(raw.cover) : '',
        finished, unchanged, stamp, lastReadAt: dateFromTimestamp(raw.readUpdateTime)
      }
    })

    const pending = drafts.filter((draft) => !draft.finished && !draft.unchanged)
    let done = 0
    options.onProgress?.(0, pending.length)
    const outcomes = await mapLimit(pending, PROGRESS_CONCURRENCY, async (draft) => {
      try {
        const result = await this.call('/book/getprogress', { bookId: draft.bookId })
        if (result.upgrade_info) upgradeNotice = true
        if (!object(result.book) || typeof result.book.progress !== 'number' ||
            !Number.isInteger(result.book.progress) || result.book.progress < 0 ||
            result.book.progress > 100) {
          throw new GatewayError('进度缺失或范围异常')
        }
        return { progress: result.book.progress, lastReadAt: dateFromTimestamp(result.book.updateTime) }
      } catch (error) {
        if (!(error instanceof GatewayError) || error.fatal) throw error
        return null
      } finally {
        options.onProgress?.(++done, pending.length)
      }
    })
    const fetched = new Map(pending.map((draft, index) => [draft.id, outcomes[index]]))

    const failedTitles: string[] = []
    const books = drafts.map((draft): Book => {
      let progress: number | null = draft.finished ? 100 : null
      let lastReadAt = draft.lastReadAt
      let syncedReadTime = draft.stamp
      if (!draft.finished && !draft.unchanged) {
        const outcome = fetched.get(draft.id)
        if (outcome) {
          progress = outcome.progress
          lastReadAt = outcome.lastReadAt ?? lastReadAt
        } else {
          // 查询失败：不记录时间戳，下次同步会重新查询这本书。
          syncedReadTime = null
          failedTitles.push(draft.title)
        }
      }
      return {
        id: draft.id, source: 'weread', title: draft.title, author: draft.author, cover: draft.cover,
        status: progress === 100 ? 'finished' : progress === 0 ? 'want' : 'reading',
        progress, lastReadAt, note: '', syncedReadTime
      }
    })

    const warnings: string[] = []
    if (failedTitles.length) {
      const names = failedTitles.slice(0, 3).map((title) => `《${title}》`).join('')
      warnings.push(failedTitles.length > 3
        ? `${names}等 ${failedTitles.length} 本书的进度暂不可用，保留已有数据。`
        : `${names}进度暂不可用，保留已有数据。`)
    }
    let readingSeconds: number | null = null
    try {
      const stats = await this.call('/readdata/detail', { mode: 'overall' })
      if (stats.upgrade_info) upgradeNotice = true
      if (typeof stats.totalReadTime !== 'number' || !Number.isFinite(stats.totalReadTime) ||
          stats.totalReadTime < 0) throw new GatewayError('缺少阅读时长')
      readingSeconds = stats.totalReadTime
    } catch (error) {
      if (!(error instanceof GatewayError) || error.fatal) throw error
      warnings.push('累计阅读时长暂不可用，保留上次数据。')
    }
    if (upgradeNotice) warnings.push('微信读书提示接口版本有更新；本次数据已照常同步，之后请留意更新本应用。')
    return {
      books, readingSeconds, warnings,
      albumCount: Array.isArray(shelf.albums) ? shelf.albums.length : 0,
      hasArticles: object(shelf.mp) && Object.keys(shelf.mp).length > 0,
      unchanged: drafts.filter((draft) => draft.unchanged).length
    }
  }
}
