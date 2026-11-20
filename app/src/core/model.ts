export type ReadingStatus = 'want' | 'reading' | 'finished'

export interface Book {
  id: string
  source: 'manual' | 'weread'
  title: string
  author: string
  cover: string
  status: ReadingStatus
  progress: number | null
  lastReadAt: string | null
  note: string
}

export interface ReadingEntry {
  date: string
  bookId: string | null
}

export interface LocalData {
  version: 1
  books: Book[]
  entries: ReadingEntry[]
  lastSyncAt: string | null
  readingSeconds: number | null
  reminder: { enabled: boolean; time: string; lastShownOn: string | null }
}

export const initialData = (): LocalData => ({
  version: 1,
  books: [],
  entries: [],
  lastSyncAt: null,
  readingSeconds: null,
  reminder: { enabled: false, time: '21:00', lastShownOn: null }
})

export function localDate(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T12:00:00`)
  return Number.isFinite(date.getTime()) && localDate(date) === value
}

export function daysSince(date: string | null, now = new Date()): number | null {
  if (!validDate(date)) return null
  const [year, month, day] = date.split('-').map(Number)
  return Math.max(0, Math.floor((
    Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) - Date.UTC(year, month - 1, day)
  ) / 86400000))
}

export function validTime(value: string): boolean {
  return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)
}

export function reminderDue(data: LocalData, now = new Date()): boolean {
  const today = localDate(now)
  const clock = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  return data.reminder.enabled && validTime(data.reminder.time) &&
    clock >= data.reminder.time && data.reminder.lastShownOn !== today &&
    !data.entries.some((entry) => entry.date === today)
}

export interface Suggestion {
  book: Book | null
  message: string
  reason: string
}

export function suggest(data: LocalData, now = new Date()): Suggestion {
  const reading = data.books.filter((book) => book.status === 'reading')
  const stale = reading.filter((book) => (daysSince(book.lastReadAt, now) ?? -1) >= 7)
    .sort((a, b) => (daysSince(b.lastReadAt, now) ?? 0) - (daysSince(a.lastReadAt, now) ?? 0))
  const recent = [...reading].sort((a, b) =>
    (daysSince(a.lastReadAt, now) ?? Infinity) - (daysSince(b.lastReadAt, now) ?? Infinity))
  const wanted = data.books.find((book) => book.status === 'want')
  const book = stale[0] ?? recent[0] ?? wanted ?? null
  let message = '想读的时候，我们就从五分钟开始。不必追赶，也不用补昨天。'
  let reason = '先在书架或想读书单放一本喜欢的书吧。'
  if (book) {
    if (stale.includes(book)) {
      message = `《${book.title}》还在那里。想继续的话，翻一页就算重新开始。`
      reason = `上次阅读是 ${daysSince(book.lastReadAt, now)} 天前；也可以换一本。`
    } else if (book.status === 'want') {
      message = `你想读的《${book.title}》，要不要一起翻开看看？`
      reason = '来自你自己收藏的想读书单，不是算法猜测。'
    } else {
      message = `要不要接着读《${book.title}》？今天读几页也很好。`
      reason = book.lastReadAt ? '接着最近的阅读节奏，慢慢来。' : '还没有最近阅读日期，暂不判断是否搁置。'
    }
  }
  if (data.entries.some((entry) => entry.date === localDate(now))) {
    message = '今天已经给自己留过阅读时间了，真好。想休息也可以，我一直在这里。'
  }
  return { book, message, reason }
}

export function recordReading(data: LocalData, bookId: string | null, now = new Date()): LocalData {
  const today = localDate(now)
  const book = bookId ? data.books.find((item) => item.id === bookId) : undefined
  if (bookId && !book) throw new Error('这本书已不在书架，请刷新后再试')
  return {
    ...data,
    entries: data.entries.some((entry) => entry.date === today)
      ? data.entries : [{ date: today, bookId }, ...data.entries],
    books: data.books.map((item) => item.id === bookId
      ? { ...item, lastReadAt: today, status: item.status === 'want' ? 'reading' : item.status } : item)
  }
}

export function mergeShelf(existing: Book[], incoming: Book[]): Book[] {
  const previous = new Map(existing.map((book) => [book.id, book]))
  const synced = incoming.map((book) => {
    const old = previous.get(book.id)
    return {
      ...book,
      note: old?.note ?? book.note,
      status: book.progress === null ? old?.status ?? book.status : book.status,
      progress: book.progress ?? old?.progress ?? null,
      lastReadAt: !old?.lastReadAt ? book.lastReadAt
        : !book.lastReadAt || old.lastReadAt > book.lastReadAt ? old.lastReadAt : book.lastReadAt
    }
  })
  const ids = new Set(synced.map((book) => book.id))
  // Keep local and previously synchronized books; a partial remote response must not erase them.
  return [...synced, ...existing.filter((book) => !ids.has(book.id))]
}
