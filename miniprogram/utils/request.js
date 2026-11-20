// 统一封装请求：自动附带 Bearer token，非 2xx 走 reject。
function request(path, method, data, retried) {
  const app = getApp()
  return app.login().then(() => new Promise((resolve, reject) => {
    const token = app.globalData.token
    wx.request({
      url: app.globalData.base + path,
      method: method || 'GET',
      data: data || {},
      timeout: 15000,
      header: {
        'Authorization': 'Bearer ' + (token || ''),
        'Content-Type': 'application/json'
      },
      success: (res) => {
        if (res.statusCode === 401 && !retried) {
          if (app.globalData.token === token) app.clearSession()
          resolve(request(path, method, data, true))
        } else if (res.statusCode < 200 || res.statusCode >= 300) {
          const error = res.data || { error: '请求失败（HTTP ' + res.statusCode + '）' }
          wx.showToast({ title: error.error || '请求失败', icon: 'none' })
          reject(error)
        } else {
          resolve(res.data)
        }
      },
      fail: () => {
        const error = { error: '无法连接后端，请检查网络和服务地址' }
        wx.showToast({ title: error.error, icon: 'none' })
        reject(error)
      }
    })
  }))
}

module.exports = { request }
