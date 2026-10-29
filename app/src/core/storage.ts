import { initialData, validDate, validTime, type Book, type LocalData, type ReadingEntry } from './model'

export const DATA_KEY = 'we-read-companion.v1'

export interface StoragePort {
  get(key: string): unknown
  set(key: string, value: string): void
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function book(value: unknown): value is Book {
  if (!object(value)) return false
  return typeof value.id === 'string' && value.id.length > 0 &&
    (value.source === 'manual' || value.source === 'weread') &&
    typeof value.title === 'string' && value.title.trim().length > 0 &&
    typeof value.author === 'string' && typeof value.cover === 'string' &&
    (value.cover === '' || value.cover.startsWith('https://')) &&
    typeof value.note === 'string' &&
    typeof value.status === 'string' && ['want', 'reading', 'finished'].includes(value.status) &&
    (value.progress === null || (Number.isInteger(value.progress) &&
      Number(value.progress) >= 0 && Number(value.progress) <= 100)) &&
    (value.lastReadAt === null || validDate(value.lastReadAt))
}

function entry(value: unknown): value is ReadingEntry {
  return object(value) && validDate(value.date) &&
    (value.bookId === null || typeof value.bookId === 'string')
}

export function parseData(raw: string): LocalData {
  let value: unknown
  try { value = JSON.parse(raw) } catch { throw new Error('本地数据不是有效 JSON，原数据未被覆盖') }
  if (!object(value) || value.version !== 1 || !Array.isArray(value.books) ||
      !value.books.every(book) || new Set(value.books.map((item) => item.id)).size !== value.books.length ||
      !Array.isArray(value.entries) || !value.entries.every(entry) ||
      new Set(value.entries.map((item) => item.date)).size !== value.entries.length ||
      !object(value.reminder) || typeof value.reminder.enabled !== 'boolean' ||
      typeof value.reminder.time !== 'string' || !validTime(value.reminder.time) ||
      !(value.reminder.lastShownOn === null || validDate(value.reminder.lastShownOn)) ||
      !(value.lastSyncAt === null || (typeof value.lastSyncAt === 'string' &&
        Number.isFinite(Date.parse(value.lastSyncAt)))) ||
      !(value.readingSeconds === null || (typeof value.readingSeconds === 'number' &&
        Number.isFinite(value.readingSeconds) && value.readingSeconds >= 0))) {
    throw new Error('本地数据格式或版本不受支持，原数据未被覆盖')
  }
  // Rebuild an allow-listed shape. Credentials and unknown fields are never imported or persisted.
  return {
    version: 1,
    books: value.books.map((item) => ({
      id: item.id, source: item.source, title: item.title, author: item.author,
      cover: item.cover, status: item.status, progress: item.progress,
      lastReadAt: item.lastReadAt, note: item.note
    })),
    entries: value.entries.map((entry) => ({ date: entry.date, bookId: entry.bookId })),
    lastSyncAt: value.lastSyncAt,
    readingSeconds: value.readingSeconds,
    reminder: {
      enabled: value.reminder.enabled,
      time: value.reminder.time,
      lastShownOn: value.reminder.lastShownOn
    }
  }
}

export function loadData(storage: StoragePort): LocalData {
  const raw = storage.get(DATA_KEY)
  if (raw === '' || raw === undefined || raw === null) return initialData()
  if (typeof raw !== 'string') throw new Error('本地存储格式异常，原数据未被覆盖')
  return parseData(raw)
}

export function saveData(storage: StoragePort, data: LocalData): void {
  const safe = parseData(JSON.stringify(data))
  storage.set(DATA_KEY, JSON.stringify(safe))
}
