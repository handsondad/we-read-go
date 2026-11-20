const app = getApp()
const { request } = require('../../utils/request')

const STATUS_TEXT = { want: '想读', reading: '在读', finished: '读完' }

Page({
  data: {
    seg: 'want',
    lists: { want: [], reading: [], finished: [] },
    counts: { want: 0, reading: 0, finished: 0 },
    showForm: false,
    editingId: 0,
    form: { title: '', author: '', status: 'want', rating: 0, note: '' },
    statusText: STATUS_TEXT,
    stars: [1, 2, 3, 4, 5]
  },
  onShow() {
    app.login().then(() => this.load()).catch(() => {})
  },
  load() {
    request('/api/booklists', 'GET')
      .then((d) => {
        const lists = { want: [], reading: [], finished: [] }
        d.forEach((it) => {
          const s = lists[it.status] ? it.status : 'want'
          lists[s].push(it)
        })
        this.setData({
          lists,
          counts: {
            want: lists.want.length,
            reading: lists.reading.length,
            finished: lists.finished.length
          }
        })
      })
      .catch(() => {})
  },
  switchSeg(e) {
    this.setData({ seg: e.currentTarget.dataset.seg })
  },
  openAdd() {
    this.setData({
      showForm: true,
      editingId: 0,
      form: { title: '', author: '', status: this.data.seg, rating: 0, note: '' }
    })
  },
  openEdit(e) {
    const id = e.currentTarget.dataset.id
    let item
    for (const k in this.data.lists) {
      item = this.data.lists[k].find((x) => x.id === id)
      if (item) break
    }
    if (!item) return
    this.setData({
      showForm: true,
      editingId: id,
      form: {
        title: item.title,
        author: item.author,
        status: item.status,
        rating: item.rating,
        note: item.note
      }
    })
  },
  closeForm() {
    this.setData({ showForm: false })
  },
  noop() {},
  onTitle(e) { this.setData({ 'form.title': e.detail.value }) },
  onAuthor(e) { this.setData({ 'form.author': e.detail.value }) },
  onNote(e) { this.setData({ 'form.note': e.detail.value }) },
  onFormStatus(e) { this.setData({ 'form.status': e.currentTarget.dataset.status }) },
  onStar(e) { this.setData({ 'form.rating': e.currentTarget.dataset.n }) },
  saveForm() {
    const f = this.data.form
    if (!f.title.trim()) {
      wx.showToast({ title: '先填书名', icon: 'none' })
      return
    }
    const payload = {
      title: f.title.trim(),
      author: f.author.trim(),
      status: f.status,
      rating: f.rating,
      note: f.note.trim()
    }
    const done = () => { this.setData({ showForm: false }); this.load() }
    if (this.data.editingId) {
      request('/api/booklists/' + this.data.editingId, 'PATCH', payload)
        .then(() => { done(); wx.showToast({ title: '已保存' }) })
        .catch((e) => wx.showToast({ title: (e && e.error) || '保存失败', icon: 'none' }))
    } else {
      request('/api/booklists', 'POST', payload)
        .then(() => { done(); wx.showToast({ title: '已添加' }) })
        .catch((e) => wx.showToast({ title: (e && e.error) || '添加失败', icon: 'none' }))
    }
  },
  deleteItem() {
    if (!this.data.editingId) return
    wx.showModal({
      title: '删除这本书？',
      success: (r) => {
        if (!r.confirm) return
        request('/api/booklists/' + this.data.editingId, 'DELETE')
          .then(() => {
            this.setData({ showForm: false })
            this.load()
            wx.showToast({ title: '已删除' })
          })
          .catch((e) => wx.showToast({ title: (e && e.error) || '删除失败', icon: 'none' }))
      }
    })
  }
})
