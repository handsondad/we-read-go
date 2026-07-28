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
    request('/api/books', 'GET')
      .then((d) => this.setData({ books: d }))
      .catch(() => {})
  },
  sync() {
    this.setData({ syncing: true })
    request('/api/sync', 'POST')
      .then(() => {
        this.setData({ syncing: false })
        this.load()
        wx.showToast({ title: '同步完成' })
      })
      .catch((e) => {
        this.setData({ syncing: false })
        wx.showToast({ title: (e && e.error) || '同步失败', icon: 'none' })
      })
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
