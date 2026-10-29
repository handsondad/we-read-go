const app = getApp()
const { request } = require('../../utils/request')

Page({
  data: {
    rep: null,
    readingText: ''
  },
  onShow() {
    app.login().then(() => this.load()).catch(() => {})
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
  },

  // ---------- canvas 分享图 ----------
  saveShareImage() {
    if (!this.data.rep) return
    wx.showLoading({ title: '生成中…' })
    this.createSelectorQuery()
      .select('#shareCanvas')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0] || !res[0].node) {
          wx.hideLoading()
          wx.showToast({ title: '生成失败', icon: 'none' })
          return
        }
        const canvas = res[0].node
        this.drawCard(canvas)
        wx.canvasToTempFilePath({
          canvas,
          success: (t) => {
            wx.hideLoading()
            this.saveToAlbum(t.tempFilePath)
          },
          fail: () => {
            wx.hideLoading()
            wx.showToast({ title: '生成失败', icon: 'none' })
          }
        })
      })
  },
  drawCard(canvas) {
    const W = 600
    const H = 800
    const dpr =
      (wx.getWindowInfo && wx.getWindowInfo().pixelRatio) ||
      (wx.getSystemInfoSync && wx.getSystemInfoSync().pixelRatio) ||
      2
    canvas.width = W * dpr
    canvas.height = H * dpr
    const ctx = canvas.getContext('2d')
    ctx.scale(dpr, dpr)

    const r = this.data.rep

    // 背景
    ctx.fillStyle = '#2b2b2b'
    ctx.fillRect(0, 0, W, H)

    // 白色圆角卡片
    this.roundRect(ctx, 40, 100, W - 80, H - 200, 24)
    ctx.fillStyle = '#ffffff'
    ctx.fill()

    // 标题
    ctx.fillStyle = '#f5a623'
    ctx.font = 'bold 28px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('读书管家 · 我的阅读战绩', W / 2, 66)

    // 连续打卡大数字
    ctx.fillStyle = '#07c160'
    ctx.font = 'bold 120px sans-serif'
    ctx.fillText(String(r.streak || 0), W / 2, 300)
    ctx.fillStyle = '#2b2b2b'
    ctx.font = '28px sans-serif'
    ctx.fillText('天连续打卡', W / 2, 350)

    // 分隔线
    ctx.strokeStyle = '#eeeeee'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(80, 400)
    ctx.lineTo(W - 80, 400)
    ctx.stroke()

    // 四项统计（两行两列）
    const stats = [
      [String(r.weekCheckins || 0) + '/7', '本周打卡'],
      [String(r.totalCheckins || 0), '累计打卡'],
      [String(r.booksReading || 0), '在读书籍'],
      [String(r.booksFinished || 0), '读完书籍']
    ]
    const colX = [W / 2 - 130, W / 2 + 130]
    const rowY = [470, 590]
    stats.forEach((s, i) => {
      const x = colX[i % 2]
      const y = rowY[Math.floor(i / 2)]
      ctx.fillStyle = '#2b2b2b'
      ctx.font = 'bold 44px sans-serif'
      ctx.fillText(s[0], x, y)
      ctx.fillStyle = '#999999'
      ctx.font = '24px sans-serif'
      ctx.fillText(s[1], x, y + 36)
    })

    // 阅读时长
    ctx.fillStyle = '#666666'
    ctx.font = '24px sans-serif'
    ctx.fillText('微信读书累计阅读 ' + this.data.readingText, W / 2, 668)

    // 底部
    ctx.fillStyle = '#aaaaaa'
    ctx.font = '22px sans-serif'
    const today = new Date()
    const dateStr =
      today.getFullYear() + '-' +
      String(today.getMonth() + 1).padStart(2, '0') + '-' +
      String(today.getDate()).padStart(2, '0')
    ctx.fillText(dateStr + ' · 长按识别小程序一起读书', W / 2, H - 60)
  },
  roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.arcTo(x + w, y, x + w, y + h, r)
    ctx.arcTo(x + w, y + h, x, y + h, r)
    ctx.arcTo(x, y + h, x, y, r)
    ctx.arcTo(x, y, x + w, y, r)
    ctx.closePath()
  },
  saveToAlbum(path) {
    wx.saveImageToPhotosAlbum({
      filePath: path,
      success: () => wx.showToast({ title: '已保存到相册' }),
      fail: (err) => {
        if (err.errMsg && err.errMsg.indexOf('auth') >= 0) {
          wx.showModal({
            title: '需要相册权限',
            content: '请在设置中允许保存到相册',
            confirmText: '去设置',
            success: (r) => {
              if (r.confirm) wx.openSetting()
            }
          })
        } else {
          wx.showToast({ title: '保存失败', icon: 'none' })
        }
      }
    })
  }
})
