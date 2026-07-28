const app = getApp()
const { request } = require('../../utils/request')

// 微信读书小程序的 AppID，用于一键跳转。如跳转失败请到微信公众平台核对最新 AppID。
const WEREAD_APPID = 'wx8d9bf9c0b4c3f5e1'

Page({
  data: {
    status: { streak: 0, todayDone: false, history: [] }
  },
  onShow() {
    app.login().then(() => this.load())
  },
  load() {
    request('/api/checkin', 'GET')
      .then((d) => this.setData({ status: d }))
      .catch(() => {})
  },
  checkIn() {
    request('/api/checkin', 'POST')
      .then(() => this.load())
      .catch(() => wx.showToast({ title: '打卡失败', icon: 'none' }))
  },
  goWeread() {
    wx.navigateToMiniProgram({ appId: WEREAD_APPID })
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
