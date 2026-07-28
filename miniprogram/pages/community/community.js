const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    board: []
  },
  onShow() {
    app.login().then(() => this.load())
  },
  load() {
    request('/api/leaderboard', 'GET')
      .then((d) => this.setData({ board: d }))
      .catch(() => {})
  }
})
