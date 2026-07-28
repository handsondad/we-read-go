const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    status: {},
    reminders: [],
    cookie: '',
    nickname: '',
    avatar: '',
    newTime: '21:00'
  },
  onShow() {
    this.loadStatus()
    this.loadReminders()
    this.loadProfile()
  },
  loadProfile() {
    request('/api/profile', 'GET')
      .then((d) => this.setData({ nickname: d.nickname || '', avatar: d.avatar || '' }))
      .catch(() => {})
  },
  onChooseAvatar(e) {
    this.setData({ avatar: e.detail.avatarUrl })
  },
  onNick(e) {
    this.setData({ nickname: e.detail.value })
  },
  saveProfile() {
    request('/api/profile', 'PATCH', { nickname: this.data.nickname, avatar: this.data.avatar })
      .then(() => wx.showToast({ title: '已保存' }))
      .catch(() => wx.showToast({ title: '保存失败', icon: 'none' }))
  },
  loadStatus() {
    request('/api/weread/status', 'GET')
      .then((d) => this.setData({ status: d }))
      .catch(() => {})
  },
  loadReminders() {
    request('/api/reminders', 'GET')
      .then((d) => this.setData({ reminders: d }))
      .catch(() => {})
  },
  onCookie(e) {
    this.setData({ cookie: e.detail.value })
  },
  saveCookie() {
    request('/api/weread/cookie', 'POST', { cookie: this.data.cookie })
      .then(() => {
        wx.showToast({ title: '已保存' })
        this.loadStatus()
      })
      .catch((e) => wx.showToast({ title: (e && e.error) || '保存失败', icon: 'none' }))
  },
  onTime(e) {
    this.setData({ newTime: e.detail.value })
  },
  addReminder() {
    request('/api/reminders', 'POST', { time: this.data.newTime })
      .then(() => this.loadReminders())
      .catch(() => {})
  },
  toggle(e) {
    const id = e.currentTarget.dataset.id
    request('/api/reminders/' + id, 'PATCH', { enabled: e.detail.value })
      .then(() => this.loadReminders())
      .catch(() => {})
  }
})
