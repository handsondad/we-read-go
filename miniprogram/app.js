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
  // 静默登录：用 wx.login 的 code 换取后端会话 token
  login() {
    return new Promise((resolve) => {
      const cached = wx.getStorageSync('token')
      if (cached) {
        this.globalData.token = cached
        resolve()
        return
      }
      wx.login({
        success: (res) => {
          wx.request({
            url: this.globalData.base + '/api/login',
            method: 'POST',
            data: { code: res.code },
            success: (r) => {
              if (r.data && r.data.token) {
                this.globalData.token = r.data.token
                wx.setStorageSync('token', r.data.token)
              }
              resolve()
            },
            fail: () => resolve()
          })
        },
        fail: () => resolve()
      })
    })
  }
})
