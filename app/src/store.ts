import { computed, reactive } from 'vue'
import {
  initialData, localDate, mergeShelf, recordReading, reminderDue, suggest, validTime,
  type Book, type LocalData, type ReadingStatus
} from './core/model'
import { loadData, parseData, saveData } from './core/storage'
import { WereadClient } from './core/weread'
import { notifyError, storage, transport } from './platform'

export const state = reactive({
  data: initialData(),
  ready: false,
  storageError: '',
  busy: false,
  connected: false,
  syncMessage: '',
  today: localDate()
})

// Until native secure storage is integrated, credentials are session-only, never uni storage.
let apiKey = ''
let active = false
let reminderTimer: ReturnType<typeof setTimeout> | undefined
export const suggestion = computed(() => suggest(state.data, new Date(`${state.today}T12:00:00`)))
export const todayDone = computed(() => state.data.entries.some((entry) => entry.date === state.today))

export function initialize(): void {
  if (state.ready) return
  try {
    state.data = loadData(storage)
    state.storageError = ''
  } catch (error) {
    state.storageError = error instanceof Error ? error.message : '读取本地数据失败'
    notifyError(error)
  }
  state.ready = true
}

function persist(data: LocalData): void {
  if (!state.ready) initialize()
  if (state.storageError) throw new Error('本地数据读取失败，为保护原数据，暂时禁止写入。请先备份并排查存储。')
  saveData(storage, data)
  state.data = data
}

export function connect(key: string): void {
  if (state.busy) throw new Error('正在同步，请完成后再更换凭证。')
  new WereadClient(key.trim(), transport)
  apiKey = key.trim()
  state.connected = true
  state.syncMessage = '已设置本次会话的 Key，尚未验证；请点击同步。'
}

export function disconnect(): void {
  if (state.busy) throw new Error('正在同步，请等待完成再清除凭证。')
  apiKey = ''
  state.connected = false
  state.syncMessage = '已从内存清除 Key，本地书架保留。'
}

export async function syncReading(): Promise<void> {
  if (state.busy) return
  if (!apiKey) throw new Error('先到设置页输入微信读书 API Key，或者直接使用本地书单。')
  if (state.storageError) throw new Error(state.storageError)
  state.busy = true
  state.syncMessage = '正在直连微信读书，同步期间请保持应用打开…'
  try {
    const result = await new WereadClient(apiKey, transport).sync()
    // Merge into the latest local state so edits made during the request are not lost.
    persist({
      ...state.data,
      books: mergeShelf(state.data.books, result.books),
      readingSeconds: result.readingSeconds ?? state.data.readingSeconds,
      lastSyncAt: new Date().toISOString()
    })
    state.syncMessage = [
      `已同步 ${result.books.length} 本电子书。`,
      ...(result.albumCount || result.hasArticles
        ? [`另有 ${result.albumCount} 个有声专辑${result.hasArticles ? '及文章收藏入口' : ''}，此版不导入。`] : []),
      ...result.warnings
    ].join('\n')
  } catch (error) {
    state.syncMessage = error instanceof Error ? error.message : '同步失败，原书架不变。'
    throw error
  } finally {
    state.busy = false
  }
}

export function addBook(title: string, author: string, status: ReadingStatus): void {
  if (!title.trim() || title.trim().length > 80) throw new Error('书名请填写 1–80 个字。')
  const book: Book = {
    id: `manual:${Date.now()}:${Math.random().toString(36).slice(2)}`,
    source: 'manual', title: title.trim(), author: author.trim(), cover: '',
    status, progress: status === 'finished' ? 100 : null, lastReadAt: null, note: ''
  }
  persist({ ...state.data, books: [book, ...state.data.books] })
}

export function updateBook(id: string, status: ReadingStatus, note: string): void {
  if (note.length > 2000) throw new Error('感想最多 2000 字。')
  persist({
    ...state.data,
    books: state.data.books.map((book) => book.id === id
      ? { ...book, status, note, progress: status === 'finished' ? 100
        : book.status === 'finished' ? null : book.progress } : book)
  })
}

export function removeBook(id: string): void {
  persist({ ...state.data, books: state.data.books.filter((book) => book.id !== id) })
}

export function readToday(bookId: string | null): void {
  state.today = localDate()
  persist(recordReading(state.data, bookId))
}

export function setReminder(enabled: boolean, time: string): void {
  if (!validTime(time)) throw new Error('请填写有效时间（HH:MM）。')
  persist({ ...state.data, reminder: { ...state.data.reminder, enabled, time } })
}

export function exportBackup(): string {
  if (state.storageError) throw new Error('读取本地数据失败，不能用空白数据生成备份。请先保留原始存储。')
  return JSON.stringify(parseData(JSON.stringify(state.data)), null, 2)
}

export function restoreBackup(raw: string): void {
  if (state.busy) throw new Error('同步期间不能替换本地数据。')
  const data = parseData(raw)
  saveData(storage, data)
  state.data = data
  state.storageError = ''
  state.today = localDate()
}

function checkReminder(): void {
  if (!active) return
  state.today = localDate()
  if (!state.storageError && reminderDue(state.data)) {
    try {
      persist({ ...state.data, reminder: { ...state.data.reminder, lastShownOn: state.today } })
      uni.showModal({ title: '小书友轻轻提醒', content: suggestion.value.message, showCancel: false })
    } catch (error) {
      notifyError(error)
    }
  }
  reminderTimer = setTimeout(checkReminder, 30000)
}

export function resume(): void {
  initialize()
  active = true
  if (reminderTimer) clearTimeout(reminderTimer)
  checkReminder()
}

export function pause(): void {
  active = false
  if (reminderTimer) clearTimeout(reminderTimer)
  reminderTimer = undefined
}
