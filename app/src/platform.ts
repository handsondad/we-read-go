import type { Transport } from './core/weread'
import type { StoragePort } from './core/storage'
import type { Book } from './core/model'

export const storage: StoragePort = {
  get: (key) => uni.getStorageSync(key),
  set: (key, value) => uni.setStorageSync(key, value)
}

export const transport: Transport = ({ url, headers, body }) => new Promise((resolve, reject) => {
  uni.request({
    url, method: 'POST', header: headers, data: body, timeout: 15000,
    success: (response) => resolve({ status: response.statusCode, data: response.data }),
    fail: () => reject(new Error('Network request failed'))
  })
})

export function notifyError(error: unknown): void {
  uni.showModal({
    title: '暂时没能完成',
    content: error instanceof Error ? error.message : '操作失败，请重试。原数据未被覆盖。',
    showCancel: false
  })
}

export function openReading(book: Book | null): void {
  const bookId = book?.source === 'weread' ? book.id.slice('weread:'.length) : null
  // #ifdef APP-PLUS
  plus.runtime.openURL(
    bookId ? `weread://reading?bId=${encodeURIComponent(bookId)}` : 'weread://',
    () => uni.showModal({
      title: '未能打开微信读书',
      content: '请检查是否已安装微信读书，或手动打开后搜索这本书。',
      showCancel: false
    })
  )
  return
  // #endif
  // #ifdef H5
  window.open('https://weread.qq.com/', '_blank', 'noopener,noreferrer')
  // #endif
}
