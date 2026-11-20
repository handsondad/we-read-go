import { describe, expect, it } from 'vitest'
import {
  daysSince, initialData, localDate, mergeShelf, recordReading, reminderDue,
  suggest, validDate, validTime, type Book
} from '../src/core/model'

const now = new Date(2026, 8, 24, 21, 0)
const book = (fields: Partial<Book> = {}): Book => ({
  id: 'weread:one', source: 'weread', title: 'A book', author: '', cover: '',
  status: 'reading', progress: 10, lastReadAt: '2026-09-18', note: '', ...fields
})

describe('gentle reading rules', () => {
  it('uses exactly seven calendar days for neglected books, not six', () => {
    const data = initialData()
    data.books = [book(), book({ id: 'weread:two', lastReadAt: '2026-09-17' })]
    expect(suggest(data, now).book?.id).toBe('weread:two')
    expect(suggest(data, now).reason).toContain('7')
    data.books.pop()
    expect(suggest(data, now).reason).not.toContain('天前')
  })
  it('does not pretend unknown dates are stale, or suggest finished books', () => {
    const data = initialData()
    data.books = [book({ status: 'finished' }), book({ id: 'manual:want', status: 'want' })]
    expect(suggest(data, now).book?.id).toBe('manual:want')
    data.books = [book({ lastReadAt: null })]
    expect(suggest(data, now).reason).toContain('暂不判断')
    expect(suggest(initialData(), now).book).toBeNull()
  })
  it('counts calendar days over DST and rejects impossible dates', () => {
    expect(daysSince('2026-03-07', new Date(2026, 2, 9))).toBe(2)
    expect(daysSince('2026-09-25', now)).toBe(0)
    expect(validDate('2026-02-29')).toBe(false)
    expect(validDate('2024-02-29')).toBe(true)
    expect(daysSince(null, now)).toBeNull()
    expect(localDate(now)).toBe('2026-09-24')
    expect(validTime('24:00')).toBe(false)
  })
  it('records once per day without fake reading time, and permits different books', () => {
    const data = initialData()
    data.books = [book({ status: 'want' }), book({ id: 'weread:two' })]
    const first = recordReading(data, 'weread:one', now)
    const second = recordReading(first, 'weread:two', now)
    expect(second.entries).toHaveLength(1)
    expect(second.books.every((item) => item.lastReadAt === '2026-09-24')).toBe(true)
    expect(second.books[0].status).toBe('reading')
    expect(second.readingSeconds).toBeNull()
    expect(suggest(second, now).message).toContain('休息')
    expect(data.entries).toHaveLength(0)
    expect(() => recordReading(data, 'gone', now)).toThrow()
  })
  it('preserves last known status/progress/date/notes when optional progress fails', () => {
    const old = book({ progress: 100, status: 'finished', note: 'keep', lastReadAt: '2026-09-24' })
    const incoming = book({ progress: null, status: 'reading', lastReadAt: '2026-09-01' })
    const merged = mergeShelf([old, book({ id: 'manual:local' })], [incoming])
    expect(merged[0]).toMatchObject({ progress: 100, status: 'finished', note: 'keep', lastReadAt: '2026-09-24' })
    expect(merged).toHaveLength(2)
    expect(mergeShelf([old], [book({ progress: 1 })])[0].progress).toBe(1)
  })
  it('reminds at or after the configured minute, once per day, excluding read days', () => {
    const data = initialData()
    data.reminder.enabled = true
    expect(reminderDue(data, new Date(2026, 8, 24, 20, 59))).toBe(false)
    expect(reminderDue(data, now)).toBe(true)
    data.reminder.lastShownOn = '2026-09-24'
    expect(reminderDue(data, now)).toBe(false)
    expect(reminderDue(data, new Date(2026, 8, 25, 21, 0))).toBe(true)
    data.reminder.lastShownOn = null
    expect(reminderDue(recordReading(data, null, now), now)).toBe(false)
  })
})
