const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    tab: 'board', // board | posts | camps
    board: [],
    posts: [],
    camps: [],
    // 心得帖表单
    draft: '',
    draftBook: '',
    posting: false,
    // 共读营表单
    showCampForm: false,
    campName: '',
    campBook: '',
    // 营详情
    campDetail: null
  },
  onShow() {
    app.login().then(() => this.loadAll())
  },
  loadAll() {
    this.loadBoard()
    this.loadPosts()
    this.loadCamps()
  },
  switchTab(e) {
    this.setData({ tab: e.currentTarget.dataset.tab, campDetail: null })
  },

  // ---------- 打卡榜 ----------
  loadBoard() {
    request('/api/leaderboard', 'GET')
      .then((d) => this.setData({ board: d }))
      .catch(() => {})
  },

  // ---------- 心得帖 ----------
  loadPosts() {
    request('/api/posts', 'GET')
      .then((d) => this.setData({ posts: d }))
      .catch(() => {})
  },
  onDraft(e) {
    this.setData({ draft: e.detail.value })
  },
  onDraftBook(e) {
    this.setData({ draftBook: e.detail.value })
  },
  publish() {
    const content = this.data.draft.trim()
    if (!content) {
      wx.showToast({ title: '先写点心得吧', icon: 'none' })
      return
    }
    if (this.data.posting) return
    this.setData({ posting: true })
    request('/api/posts', 'POST', { content, bookTitle: this.data.draftBook.trim() })
      .then(() => {
        this.setData({ draft: '', draftBook: '', posting: false })
        this.loadPosts()
        wx.showToast({ title: '已发布' })
      })
      .catch((e) => {
        this.setData({ posting: false })
        wx.showToast({ title: (e && e.error) || '发布失败', icon: 'none' })
      })
  },
  toggleLike(e) {
    const id = e.currentTarget.dataset.id
    request('/api/posts/' + id + '/like', 'POST', {})
      .then((d) => {
        const posts = this.data.posts.map((p) =>
          p.id === id ? Object.assign({}, p, { likes: d.likes, likedByMe: d.liked }) : p
        )
        this.setData({ posts })
      })
      .catch(() => {})
  },

  // ---------- 共读营 ----------
  loadCamps() {
    request('/api/camps', 'GET')
      .then((d) => this.setData({ camps: d }))
      .catch(() => {})
  },
  toggleCampForm() {
    this.setData({ showCampForm: !this.data.showCampForm })
  },
  onCampName(e) {
    this.setData({ campName: e.detail.value })
  },
  onCampBook(e) {
    this.setData({ campBook: e.detail.value })
  },
  createCamp() {
    const name = this.data.campName.trim()
    if (!name) {
      wx.showToast({ title: '给共读营起个名字', icon: 'none' })
      return
    }
    request('/api/camps', 'POST', { name, bookTitle: this.data.campBook.trim() })
      .then(() => {
        this.setData({ campName: '', campBook: '', showCampForm: false })
        this.loadCamps()
        wx.showToast({ title: '已创建' })
      })
      .catch((e) => wx.showToast({ title: (e && e.error) || '创建失败', icon: 'none' }))
  },
  joinCamp(e) {
    const id = e.currentTarget.dataset.id
    request('/api/camps/' + id + '/join', 'POST', {})
      .then(() => {
        this.loadCamps()
        wx.showToast({ title: '加入成功' })
      })
      .catch(() => {})
  },
  openCamp(e) {
    const id = e.currentTarget.dataset.id
    request('/api/camps/' + id, 'GET')
      .then((d) => this.setData({ campDetail: d }))
      .catch(() => {})
  },
  closeCamp() {
    this.setData({ campDetail: null })
  }
})
