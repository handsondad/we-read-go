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
    this.load()
  },
  load() {
    const STATUS = { reading: '在读', finished: '读完', want: '想读' }
    request('/api/books', 'GET')
      .then((d) => this.setData({ books: d.map((b) => Object.assign({}, b, {
        statusText: STATUS[b.status] || b.status
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
    this._syncTimer = setInterval(() => {
      request('/api/weread/status', 'GET')
        .then((s) => {
          if (!s.syncing) {
            if (this._syncTimer) clearInterval(this._syncTimer)
            this._syncTimer = null
            this.setData({ syncing: false })
            this.load()
            if (s.lastSyncError) {
              wx.showToast({ title: '同步失败：' + s.lastSyncError, icon: 'none' })
            } else {
              wx.showToast({ title: '同步完成' })
            }
          }
        })
        .catch(() => {})  // 轮询失败不打断，继续等待
    }, 1200)
  },
  onUnload() {
    if (this._syncTimer) clearInterval(this._syncTimer)
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
