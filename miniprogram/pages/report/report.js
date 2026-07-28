const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    rep: null,
    readingText: ''
  },
  onShow() {
    app.login().then(() => this.load())
  },
  load() {
    request('/api/report', 'GET')
      .then((d) => {
        const sec = d.readingSeconds || 0
        const h = Math.floor(sec / 3600)
        const m = Math.floor((sec % 3600) / 60)
        const txt = h > 0 ? h + ' 小时 ' + m + ' 分' : m + ' 分'
        this.setData({ rep: d, readingText: txt })
      })
      .catch(() => {})
  },
  goCommunity() {
    wx.navigateTo({ url: '/pages/community/community' })
  },
  onShareAppMessage() {
    const r = this.data.rep || {}
    return {
      title: '我已连续打卡 ' + (r.streak || 0) + ' 天，一起来读书！',
      path: '/pages/index/index'
    }
  }
})
