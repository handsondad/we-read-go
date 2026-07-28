// 统一封装请求：自动附带 Bearer token，非 2xx 走 reject。
function request(path, method, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: getApp().globalData.base + path,
      method: method || 'GET',
      data: data || {},
      header: {
        'Authorization': 'Bearer ' + (getApp().globalData.token || ''),
        'Content-Type': 'application/json'
      },
      success: (res) => {
        if (res.statusCode >= 400) reject(res.data || { error: 'http ' + res.statusCode })
        else resolve(res.data)
      },
      fail: reject
    })
  })
}

module.exports = { request }
