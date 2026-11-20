const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    books: [],
    newTitle: '',
    newAuthor: '',
    syncing: false
  },
  onShow() {
    this._hidden = false
    this.load()
    request('/api/weread/status', 'GET').then((status) => {
      if (status.syncing && !this._hidden) {
        this.setData({ syncing: true })
        this._pollSync()
      }
    }).catch(() => {})
  },
  load() {
    const STATUS = { reading: '在读', finished: '读完', want: '想读' }
    request('/api/books', 'GET')
      .then((d) => this.setData({ books: d.map((b) => Object.assign({}, b, {
        statusText: STATUS[b.status] || b.status,
        readHint: b.daysSinceRead >= 7 ? `上次阅读是 ${b.daysSinceRead} 天前，今天从一页开始就好` : ''
      })) }))
      .catch(() => {})
  },
  sync() {
    if (this.data.syncing) return
    this.setData({ syncing: true })
    request('/api/sync', 'POST')
      .then((d) => {
        if (d && d.ok === false) {
          this.setData({ syncing: false })
          wx.showToast({ title: d.message || '同步失败', icon: 'none' })
          return
        }
        this._pollSync()
      })
      .catch((e) => {
        this.setData({ syncing: false })
        wx.showToast({ title: (e && e.error) || '同步失败', icon: 'none' })
      })
  },
  _pollSync() {
    if (this._hidden || this._syncTimer) return
    this._pollStartedAt = this._pollStartedAt || Date.now()
    this._syncTimer = setTimeout(() => {
      this._syncTimer = null
      if (Date.now() - this._pollStartedAt > 10 * 60 * 1000) {
        this._stopPolling()
        wx.showToast({ title: '同步耗时较长，请稍后重新进入书架查看', icon: 'none' })
        return
      }
      request('/api/weread/status', 'GET')
        .then((s) => {
          if (this._hidden) return
          if (!s.syncing) {
            this._stopPolling()
            this.load()
            if (s.lastSyncError) {
              wx.showToast({ title: '同步提示：' + s.lastSyncError, icon: 'none' })
            } else {
              wx.showToast({ title: '同步完成' })
            }
          } else {
            this._pollSync()
          }
        })
        .catch(() => this._stopPolling())
    }, 1200)
  },
  _stopPolling() {
    if (this._syncTimer) clearTimeout(this._syncTimer)
    this._syncTimer = null
    this._pollStartedAt = null
    this.setData({ syncing: false })
  },
  onHide() {
    this._hidden = true
    this._stopPolling()
  },
  onUnload() {
    this.onHide()
  },
  onTitle(e) {
    this.setData({ newTitle: e.detail.value })
  },
  onAuthor(e) {
    this.setData({ newAuthor: e.detail.value })
  },
  addManual() {
    if (!this.data.newTitle) {
      wx.showToast({ title: '请输入书名', icon: 'none' })
      return
    }
    request('/api/books', 'POST', {
      title: this.data.newTitle,
      author: this.data.newAuthor
    })
      .then(() => {
        this.setData({ newTitle: '', newAuthor: '' })
        this.load()
      })
      .catch(() => {})
  }
})
