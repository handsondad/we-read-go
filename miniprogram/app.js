App({
  globalData: {
    // 后端地址：真机需为公网 HTTPS 域名；开发者工具可填本机地址
    base: 'http://localhost:8080',
    token: '',
    openid: ''
  },
  onLaunch() {
    const t = wx.getStorageSync('token')
    if (t) this.globalData.token = t
  },
  login() {
    if (this._loginPromise) return this._loginPromise
    const cached = wx.getStorageSync('token')
    if (cached) {
      this.globalData.token = cached
      return Promise.resolve()
    }
    const attempt = new Promise((resolve, reject) => {
      wx.login({
        timeout: 10000,
        success: (res) => {
          if (!res.code) {
            reject({ error: '微信未返回登录凭证，请重新进入小程序' })
            return
          }
          wx.request({
            url: this.globalData.base + '/api/login',
            method: 'POST',
            timeout: 15000,
            data: { code: res.code },
            success: (r) => {
              if (r.statusCode >= 200 && r.statusCode < 300 && r.data && r.data.token) {
                this.globalData.token = r.data.token
                wx.setStorageSync('token', r.data.token)
                resolve()
              } else {
                reject({ error: (r.data && r.data.error) || '登录失败，请检查小程序 AppID 和后端配置' })
              }
            },
            fail: () => reject({ error: '无法连接后端，请检查服务地址、网络和合法域名配置' })
          })
        },
        fail: () => reject({ error: '微信登录失败，请稍后重新进入小程序' })
      })
    })
    this._loginPromise = attempt.catch((error) => {
      wx.showModal({ title: '暂时无法登录', content: error.error, showCancel: false })
      throw error
    }).then(() => {
      this._loginPromise = null
    }, (error) => {
      this._loginPromise = null
      throw error
    })
    return this._loginPromise
  },
  clearSession() {
    this.globalData.token = ''
    wx.removeStorageSync('token')
  }
})
