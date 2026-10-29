const app = getApp()
const { request } = require('../../utils/request')

// 微信读书小程序的 AppID，用于一键跳转。如跳转失败请到微信公众平台核对最新 AppID。
const WEREAD_APPID = 'wx8d9bf9c0b4c3f5e1'

Page({
  data: {
    companion: {
      state: 'quiet',
      message: '今天也可以慢慢来。想读的时候，我们就从 5 分钟开始。',
      gentlePrompt: '今天不必补昨天，愿意翻开一页就很好。',
      todayDone: false,
      streak: 0,
      recommendation: null
    }
  },
  onShow() {
    app.login().then(() => this.load()).catch(() => {})
  },
  load() {
    request('/api/companion', 'GET')
      .then((d) => this.setData({ companion: d }))
      .catch(() => {})
  },
  checkIn() {
    request('/api/checkin', 'POST')
      .then(() => this.load())
      .catch(() => wx.showToast({ title: '记录失败，请稍后再试', icon: 'none' }))
  },
  goWeread() {
    wx.navigateToMiniProgram({
      appId: WEREAD_APPID,
      fail: () => wx.showToast({ title: '暂时无法跳转，请直接打开微信读书', icon: 'none' })
    })
  },
  goBookshelf() {
    wx.navigateTo({ url: '/pages/bookshelf/bookshelf' })
  },
  goReport() {
    wx.navigateTo({ url: '/pages/report/report' })
  },
  goCommunity() {
    wx.navigateTo({ url: '/pages/community/community' })
  },
  goBooklist() {
    wx.navigateTo({ url: '/pages/booklist/booklist' })
  },
  goProfile() {
    wx.navigateTo({ url: '/pages/profile/profile' })
  }
})
