// Node's built-in runner checks logic without requiring a WeChat account.
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const root = path.join(__dirname, 'miniprogram')
const flush = () => new Promise((resolve) => setImmediate(resolve))

function environment() {
  const storage = new Map()
  const messages = []
  let app
  const wx = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    showToast: (message) => messages.push(message),
    showModal: (message) => messages.push(message),
    login: ({ success }) => success({ code: 'test-code' }),
    request: ({ success }) => success({ statusCode: 200, data: { token: 'new-token' } })
  }
  const sandbox = { wx, App: (value) => { app = value }, getApp: () => app, Promise }
  vm.runInNewContext(fs.readFileSync(path.join(root, 'app.js'), 'utf8'), sandbox)
  const module = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(root, 'utils', 'request.js'), 'utf8'),
    { ...sandbox, module })
  return { app, wx, storage, messages, request: module.exports.request }
}

function loadPage(name, env, timers = {}) {
  let page
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages', name, name + '.js'), 'utf8'), {
    wx: env.wx,
    getApp: () => env.app,
    require: () => ({ request: env.request }),
    Page: (value) => { page = value },
    setTimeout, clearTimeout, ...timers
  })
  page.setData = (values) => Object.assign(page.data, values)
  return page
}

test('all six pages parse and every WXML event has a handler', () => {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'))
  for (const route of config.pages) {
    const name = route.split('/')[1]
    const page = loadPage(name, environment())
    const wxml = fs.readFileSync(path.join(root, route + '.wxml'), 'utf8')
    for (const match of wxml.matchAll(/(?:bind|catch)(?::)?[\w-]+="(\w+)"/g)) {
      assert.equal(typeof page[match[1]], 'function', route + ': ' + match[1])
    }
    JSON.parse(fs.readFileSync(path.join(root, route + '.json'), 'utf8'))
  }
})

test('concurrent requests share one login and send the returned token', async () => {
  const env = environment()
  let logins = 0
  let finish
  env.wx.login = (options) => { logins++; finish = options.success }
  const calls = []
  env.wx.request = (options) => {
    calls.push(options)
    options.success({ statusCode: 200, data: options.url.endsWith('/api/login')
      ? { token: 'real-session' } : { ok: true } })
  }
  const first = env.request('/api/books')
  const second = env.request('/api/profile')
  finish({ code: 'code' })
  await Promise.all([first, second])
  assert.equal(logins, 1)
  assert.equal(calls.length, 3)
  assert.equal(calls[1].header.Authorization, 'Bearer real-session')
  assert.equal(calls[2].header.Authorization, 'Bearer real-session')
})

test('failed login is visible, does not call protected APIs, and permits retry', async () => {
  const env = environment()
  env.wx.request = (options) => options.success({
    statusCode: 400, data: { error: 'WX_APPID / WX_APPSECRET 未配置' }
  })
  await assert.rejects(env.request('/api/books'))
  assert.equal(env.messages[0].title, '暂时无法登录')
  assert.match(env.messages[0].content, /WX_APPID/)
  assert.equal(env.app._loginPromise, null)
  assert.equal(env.storage.has('token'), false)
  env.wx.request = (options) => options.success({ statusCode: 200, data: { token: 'retry' } })
  await env.app.login()
  assert.equal(env.storage.get('token'), 'retry')
})

test('expired session is refreshed once and retries cannot loop', async () => {
  const env = environment()
  env.storage.set('token', 'expired')
  let loginCalls = 0
  let protectedCalls = 0
  env.wx.request = (options) => {
    if (options.url.endsWith('/api/login')) {
      loginCalls++
      options.success({ statusCode: 200, data: { token: 'fresh' } })
    } else {
      protectedCalls++
      options.success({ statusCode: 401, data: { error: 'expired' } })
    }
  }
  await assert.rejects(env.request('/api/profile'))
  assert.equal(loginCalls, 1)
  assert.equal(protectedCalls, 2)
})

test('network failures are visible instead of showing an empty success state', async () => {
  const env = environment()
  env.storage.set('token', 'cached')
  env.wx.request = ({ fail }) => fail({ errMsg: 'offline' })
  await assert.rejects(env.request('/api/books'))
  assert.match(env.messages[0].title, /无法连接后端/)
})

test('reminder subscription uses server template and never promises daily delivery', () => {
  const env = environment()
  const page = loadPage('profile', env)
  page.authorizeReminder()
  assert.match(env.messages[0].title, /尚未配置/)
  page.data.reminderConfig = { enabled: true, templateId: 'approved-template' }
  env.wx.requestSubscribeMessage = ({ tmplIds, success }) => {
    assert.equal(tmplIds[0], 'approved-template')
    success({ 'approved-template': 'accept' })
  }
  page.authorizeReminder()
  assert.match(env.messages[1].content, /一次性/)
})

test('sync polling stops after a network failure and when page is hidden', async () => {
  const env = environment()
  let callback
  let cleared = 0
  const page = loadPage('bookshelf', {
    ...env, request: () => Promise.reject(new Error('offline'))
  }, {
    setTimeout: (fn) => { callback = fn; return 1 },
    clearTimeout: () => { cleared++ }
  })
  page.data.syncing = true
  page._pollSync()
  callback()
  await flush()
  assert.equal(page.data.syncing, false)
  assert.equal(page._syncTimer, null)
  page._pollSync()
  page.onHide()
  assert.equal(cleared, 1)
  assert.equal(page._hidden, true)
})

test('home records reading and reloads the companion response', async () => {
  const env = environment()
  const calls = []
  const page = loadPage('index', {
    ...env,
    request: async (route, method) => {
      calls.push([route, method])
      return route === '/api/checkin'
        ? { ok: true } : { todayDone: true, message: '读过啦' }
    }
  })
  page.checkIn()
  await flush()
  assert.equal(calls[0][0], '/api/checkin')
  assert.equal(calls[0][1], 'POST')
  assert.equal(page.data.companion.todayDone, true)
})

test('saving an API Key clears the sensitive input and refreshes binding status', async () => {
  const env = environment()
  let saved
  const page = loadPage('profile', {
    ...env,
    request: async (route, method, body) => {
      if (route === '/api/weread/api-key') saved = body.apiKey
      return { hasApiKey: true }
    }
  })
  page.data.apiKey = 'wrk-test'
  page.saveApiKey()
  await flush()
  assert.equal(saved, 'wrk-test')
  assert.equal(page.data.apiKey, '')
  assert.equal(page.data.status.hasApiKey, true)
})

test('successful sync polling reloads books and stops scheduling', async () => {
  const env = environment()
  let callback
  const page = loadPage('bookshelf', {
    ...env,
    request: async (route) => route === '/api/weread/status'
      ? { syncing: false }
      : [{ id: 1, title: '测试', status: 'reading', daysSinceRead: 12 }]
  }, {
    setTimeout: (fn) => { callback = fn; return 1 },
    clearTimeout: () => {}
  })
  page.data.syncing = true
  page._pollSync()
  callback()
  await flush()
  assert.equal(page.data.syncing, false)
  assert.equal(page._syncTimer, null)
  assert.equal(page.data.books[0].statusText, '在读')
  assert.match(page.data.books[0].readHint, /12/)
})
