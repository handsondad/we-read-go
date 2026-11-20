const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    status: {},
    reminders: [],
    apiKey: '',
    cookie: '',
    legacyExpanded: false,
    reminderConfig: { enabled: false, templateId: '' },
    nickname: '',
    avatar: '',
    newTime: '21:00'
  },
  onShow() {
    app.login().then(() => {
      this.loadStatus()
      this.loadReminders()
      this.loadProfile()
      request('/api/reminders/config', 'GET')
        .then((reminderConfig) => this.setData({ reminderConfig }))
        .catch(() => {})
    }).catch(() => {})
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
  onApiKey(e) {
    this.setData({ apiKey: e.detail.value })
  },
  saveApiKey() {
    if (!this.data.apiKey.trim()) {
      wx.showToast({ title: '请先粘贴 API Key', icon: 'none' })
      return
    }
    request('/api/weread/api-key', 'POST', { apiKey: this.data.apiKey })
      .then(() => {
        this.setData({ apiKey: '' })
        wx.showToast({ title: '已加密保存' })
        this.loadStatus()
      })
      .catch((e) => wx.showToast({ title: (e && e.error) || '保存失败', icon: 'none' }))
  },
  toggleLegacy() {
    this.setData({ legacyExpanded: !this.data.legacyExpanded })
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
      .then(() => {
        this.loadReminders()
        wx.showToast({ title: '时间已保存，推送需授权', icon: 'none' })
      })
      .catch(() => {})
  },
  authorizeReminder() {
    const config = this.data.reminderConfig
    if (!config.enabled) {
      wx.showToast({ title: '服务端尚未配置订阅消息模板', icon: 'none' })
      return
    }
    wx.requestSubscribeMessage({
      tmplIds: [config.templateId],
      success: (result) => {
        wx.showModal({
          title: result[config.templateId] === 'accept' ? '已获得本次订阅授权' : '未获得订阅授权',
          content: '普通订阅消息通常是一次性授权，并不代表每天都能推送；后续提醒需要再次授权。',
          showCancel: false
        })
      },
      fail: () => wx.showToast({ title: '订阅授权失败，请在微信中重试', icon: 'none' })
    })
  },
  toggle(e) {
    const id = e.currentTarget.dataset.id
    request('/api/reminders/' + id, 'PATCH', { enabled: e.detail.value })
      .then(() => this.loadReminders())
      .catch(() => {})
  }
})
