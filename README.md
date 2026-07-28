# 微信读书管家（we-read-go）

> 名字里的 **go** 取「跳转 / 去读」之意，不是编程语言。后端用 **Python** 实现。

一个围绕「微信读书」的**阅读习惯管家 + 共读社区**小程序配套后端：

- 用小程序做**提醒、打卡、连胜、阅读报告、共读榜**；
- 一键 `navigateToMiniProgram` **跳转微信读书**继续阅读；
- 进阶能力：粘贴微信读书网页 Cookie，由后端同步书架 / 进度 / 阅读统计（**非官方接口，可降级**，失败不影响核心打卡）。

> ⚠️ 微信读书**没有**面向第三方的官方开放 API。同步功能是对 `weread.qq.com` 网页端接口的逆向调用，
> 随时可能随网页改版失效，且需要用户自行导出 Cookie，门槛较高、存在账号安全风险。
> 因此首版核心闭环（打卡 / 提醒 / 报告 / 社区）**不依赖** weread 数据，Cookie 同步仅作进阶能力。

## 目录结构

```
backend/                  Python 后端（标准库 http.server + sqlite3）
  config.py               环境变量配置
  db.py                   SQLite 建表
  crypto.py               AES 加密（Cookie 入库前加密，依赖 cryptography）
  weread.py               微信读书非官方接口客户端（可降级）
  services.py             业务逻辑：登录/同步/打卡/提醒/报告/社区
  server.py               HTTP 入口 + 路由 + 每分钟提醒调度
miniprogram/              微信小程序前端（首页打卡 / 书架 / 设置 / 报告 / 共读榜）
```

## 快速开始（后端）

```bash
cd we-read-go
pip install -r requirements.txt        # 仅 cryptography 一个外部依赖
python backend/server.py               # 默认监听 0.0.0.0:8080，生成 we_read.db
```

健康检查：

```bash
curl http://127.0.0.1:8080/health
# {"status":"ok"}
```

## 配置（环境变量）

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `SERVER_ADDR` | 监听地址 | `0.0.0.0:8080` |
| `DB_PATH` | SQLite 文件路径 | `we_read.db` |
| `WX_APPID` | 微信小程序 AppID | 空 |
| `WX_APPSECRET` | 微信小程序 AppSecret | 空 |
| `WX_TEMPLATE_ID` | 订阅消息模板 ID（提醒推送用） | 空 |
| `ENCRYPT_KEY` | 加密微信读书 Cookie 的种子（请换成强随机串） | `change-me-32-byte-key-1234567890` |
| `WEREAD_UA` | 请求 weread 时的 User-Agent | 内置 |
| `CRON_SECRET` | 预留的内部触发密钥 | `change-me-cron-secret` |

> 提醒推送需要 `WX_APPID` / `WX_APPSECRET` / `WX_TEMPLATE_ID` 三者齐备才会启用；
> 缺失时仅跳过推送，不影响其他功能。

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/login` | 用 `wx.login` 的 code 换 token 与用户 |
| POST | `/api/weread/cookie` | 保存微信读书 Cookie（加密存储） |
| GET | `/api/weread/status` | 同步状态 |
| POST | `/api/sync` | 触发同步（异步，前端轮询 `/api/weread/status` 获取进度与错误） |
| GET/POST | `/api/books` | 列出 / 新增（手动）书籍 |
| POST/GET | `/api/checkin` | 打卡 / 打卡状态（含连胜、近 30 天历史） |
| GET/POST | `/api/reminders` | 列出 / 新增提醒时间 |
| PATCH | `/api/reminders/{id}` | 启停提醒 |
| GET | `/api/report` | 阅读可视化报告（连胜/打卡/书目/时长） |
| GET | `/api/leaderboard` | 共读打卡排行榜（社区雏形） |
| GET/POST | `/api/posts` | 心得帖列表（`?campId=` 可按营过滤）/ 发帖 |
| POST | `/api/posts/{id}/like` | 点赞 / 取消点赞（切换式） |
| GET/POST | `/api/camps` | 共读营列表 / 创建（创建者自动入营） |
| GET | `/api/camps/{id}` | 营详情（成员打卡榜 + 营内心得） |
| POST | `/api/camps/{id}/join` | 加入共读营 |
| GET/POST | `/api/booklists` | 书单列表 / 添加（状态 want/reading/finished、评分 0-5、感想） |
| PATCH | `/api/booklists/{id}` | 更新书单条目（状态/评分/感想/书名/作者） |
| DELETE | `/api/booklists/{id}` | 删除书单条目 |
| GET/PATCH | `/api/profile` | 读取 / 设置昵称头像 |
| GET | `/health` | 健康检查 |

鉴权：除 `/health` 外，所有接口需在 Header 带 `Authorization: Bearer <token>`。

## 小程序前端

用微信开发者工具导入 `miniprogram/`，在 `app.js` 把 `globalData.base` 指向后端地址，
`project.config.json` 换成你的 AppID，开发阶段勾选「不校验合法域名」即可联调。

跳转微信读书依赖 `app.json` 的 `navigateToMiniProgramAppIdList`，其中的微信读书 AppID
（`wx8d9bf9c0b4c3f5e1`）请到公众平台核对最新值。

## 后续演进

- ✅ 阅读可视化报告（`/api/report` + `pages/report`）
- ✅ 共读打卡榜（`/api/leaderboard` + `pages/community`）
- ✅ 心得帖（发帖 + 点赞，`posts`/`post_likes` 表）
- ✅ 共读营（创建/加入/营内榜单与心得，`camps`/`camp_members` 表）
- ✅ canvas 分享图片（报告页生成战绩卡片保存到相册）
- ✅ 书单（想读/在读/读完三段、星级评分、感想，独立可读写，`booklists` 表 + `pages/booklist`）
- ✅ 真实昵称头像（设置页 `chooseAvatar` + 昵称填写组件；打卡榜 / 心得帖 / 共读营显示头像）
- ✅ 稳定的微信读书同步（后台线程异步执行，瞬时网络错误自动重试退避；Cookie 失效通过 302 跳转 / 登录页 HTML / 错误码 JSON 识别并落库 `lastSyncError`，前端轮询展示失败原因，绝不拖垮核心打卡）。
