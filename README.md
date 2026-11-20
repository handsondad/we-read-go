# 小书友 · 微信读书伙伴（we-read-go）

新版在 `app\`：**uni-app + Vue 3 + TypeScript，本地优先，不依赖自建后端**。
小书友根据真实阅读进度、最近阅读日期和自己的想读书单，温柔地建议下一本书。不罚漏读、不要求补卡、不设连续天数排行榜。

旧版小程序已提交并推送到 [`wechat-miniprogram` 分支](https://github.com/handsondad/we-read-go/tree/wechat-miniprogram)，
保存点为 `54eb281`。新版开发在 `uni-app-local-first` 分支；旧的 `backend\`、`miniprogram\` 保留参考，新应用不调用它们。

## 新版：先在本地体验

需要 Node.js 20.19+（当前在 Node.js 24 下验证）。PowerShell：

```powershell
Set-Location app
npm.cmd ci
npm.cmd run dev:h5 -- --host 127.0.0.1
```

打开终端显示的本地地址。**不填 API Key 也能使用**：到「想读」新增书目，回到「伙伴」查看建议，记录今天读过，到「足迹」查看记录。
刷新后书目和足迹保留在同一个浏览器/应用的本地存储；没有演示书架伪装成真实数据。

| 页面 | 已落地能力 |
| --- | --- |
| 伙伴 | 小书友形象、根据书单的建议、搁置满 7 天的温柔提示、今天读过的反馈 |
| 书架 | 直连官方接口同步电子书/进度，搜索，保留上次同步数据，打开微信读书 |
| 想读 | 本地加书、想读/在读/读完状态、简短感想、删除本地条目 |
| 足迹 | 本机阅读日、读完书目数、官方累计时长、不会因漏读倒退的阅读角成长 |
| 设置 | 会话 Key、应用内提醒时间、不含 Key 的备份文本生成与校验恢复 |

「我今天读过了」是自己记录的一天，不自动假定为微信读书实际阅读时长，也不回写微信读书。
每天只记一个阅读日；同一天仍可在书架记录不同书目的最近阅读日期。
书架同步只导入电子书，不把有声专辑/文章入口伪装成电子书；未出现在远端响应中的旧书保留，不自动删除。
官方书目的状态可能被真实同步更新，本地感想会保留；可选进度/时长查询失败会给出提示，保留已有数值。
认证或版本升级错误中止本次同步，不写入半份结果。

### 连接官方微信读书

自行在[微信读书 Skills 页面](https://weread.qq.com/r/weread-skills)登录获取 `wrk-` 开头的 API Key，
在「设置」输入后同步。**不要把 Key 发到聊天、截图或 Git**。
应用用 Bearer Key 直连 `https://i.weread.qq.com/api/agent/gateway`，不经过我们的服务器或第三方代理。
**尚未用真实账号验证接口；H5 直连可能受 CORS 限制**，遇到跨域错误需在 App 真机验证，不能据浏览器预览认定账号不可用。

隐私与当前边界：

- **API Key 只留在本次运行内存中**，重新启动需再输入；未实现并验证原生安全存储前，不用明文持久化替代。
- 阅读数据存在本机；备份不包含 Key。卸载、清理应用/浏览器存储会丢失记录，备份含书名和日期，请自行妥善保管。
- 图片封面直接请求原始 HTTPS 地址，离线时图片可能不可用。本地书单和记录不依赖联网。
- 现在的提醒**仅应用前台/重新打开时检查**：到达配置时间、当天未记录且未提醒时弹出，每天最多一次。**不是关掉 App 后的系统通知**。
- App 通过 `weread://` 尝试打开微信读书，指定书目的协议跳转仍需真机确认；失败时请手动打开后搜索。H5 打开微信读书官网。
- 当前没有自建账号、云同步、多人社区或大模型调用；不声称支持所有 uni-app 平台，本轮目标是 H5 预览和 Android/iOS App 资源。

### 校验与 App 构建

在 `app\` 下执行：

```powershell
npm.cmd test
npm.cmd run type-check
npm.cmd run build:h5
npm.cmd run build:app
```

测试覆盖 7 天推荐阈值、日历日期、一天一次记录、提醒、存储损坏保护、备份、同步并发、
凭证不落盘、可选接口失败保留数据、官方参数和进度单位。H5 产物在 `app\dist\build\h5`。

`build:app` 产出 `app\dist\build\app` 的 **App 前端资源，不是 APK/IPA**。
实际安装仍需 HBuilderX，申请自己的 DCloud AppID、配置应用标识/签名，按官方 CLI 工程流程真机运行/打包；
`app\src\manifest.json` 的 AppID 故意留空，不替用户虚构。
Android/iOS 真机联网、协议唤起、原生安全存储、后台本地通知和最终安装包尚未验证。

---

## 旧版：微信小程序 + Python 服务

> 名字里的 **go** 取「跳转 / 去读」之意，不是编程语言。以下是保留的旧版说明，后端用 **Python** 实现。

一个围绕「微信读书」的**阅读习惯管家 + 共读社区**小程序配套后端：

- 用小程序做**提醒、打卡、连胜、阅读报告、共读榜**；
- 首页有一位温柔的「小书友」，根据书架和阅读进度推荐今天读哪本，不用补打卡；
- 一键 `navigateToMiniProgram` **跳转微信读书**继续阅读；
- 使用微信读书官方 Skills/API Key 同步书架 / 进度 / 阅读统计，识别久未翻开的书；
- 旧版网页 Cookie 同步暂时保留作兼容，官方 API Key 优先。

官方 API Key 可在[微信读书 Skills 页面](https://weread.qq.com/r/weread-skills)获取。API Key 在本服务端加密保存；
阅读提醒不责备漏读，推荐理由来自最近阅读日期、当前进度或用户自己的「想读」书单。

## 目录结构

```
backend/                  Python 后端（标准库 http.server + sqlite3）
  config.py               环境变量配置
  db.py                   SQLite 建表
  crypto.py               AES 加密（API Key / Cookie 入库前加密，依赖 cryptography）
  weread.py               微信读书官方 Skills API 与旧版 Cookie 客户端
  services.py             业务逻辑：登录/同步/打卡/提醒/报告/社区
  server.py               HTTP 入口 + 路由 + 每分钟提醒调度
miniprogram/              微信小程序前端（首页打卡 / 书架 / 设置 / 报告 / 共读榜）
```

## 快速开始（后端）

在仓库根目录打开 PowerShell，设置本次进程所需环境变量后启动：

```powershell
python -m pip install -r requirements.txt
$env:WX_APPID = "你的小程序 AppID"
$env:WX_APPSECRET = "你的小程序 AppSecret"
$env:ENCRYPT_KEY = "替换为你自行生成并安全保管的强随机密钥"
python backend\server.py
```

`ENCRYPT_KEY` 必填；重启时使用同一个密钥，否则无法解密已保存的微信读书凭证。
密钥、AppSecret 和 API Key 不要提交到 Git，也不要发到聊天中。程序读取进程环境变量，**不会自动加载 `.env` 文件**。
默认监听 `0.0.0.0:8080`，在当前目录创建 `we_read.db`。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
# status: ok
```

健康检查通过只代表后端启动，**不代表已完成微信登录、微信读书同步或消息推送联调**。

## 配置（环境变量）

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `ADDR` | 监听地址 | `0.0.0.0:8080` |
| `DB_PATH` | SQLite 文件路径 | `we_read.db` |
| `WX_APPID` | 微信小程序 AppID | 空 |
| `WX_APPSECRET` | 微信小程序 AppSecret | 空 |
| `WX_TEMPLATE_ID` | 订阅消息模板 ID（提醒推送用） | 空 |
| `ENCRYPT_KEY` | 加密微信读书 API Key / Cookie 的种子，必须配置且重启保持一致 | 无 |
| `WEREAD_UA` | 旧版 Cookie 接口的 User-Agent | 内置 |

> 提醒推送需要 `WX_APPID` / `WX_APPSECRET` / `WX_TEMPLATE_ID` 三者齐备才会启用；
> 缺失时设置页会显示“目前只能保存提醒时间”，不影响其他功能。
> 模板字段须对应 `thing1`（20 字以内的提醒文案）和 `time2`（提醒时间），不能填其他结构的模板。
> 用户还须在设置页点「授权下一次微信提醒」；普通订阅一般为一次性额度，并非永久日推送权限。
> 调度使用后端系统本地时区，每分钟检查；同用户每日最多发送一次，今日已记录阅读则不发。

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/login` | 用 `wx.login` 的 code 换 token 与用户 |
| POST | `/api/weread/api-key` | 保存微信读书官方 API Key（加密存储） |
| POST | `/api/weread/cookie` | 保存旧版微信读书 Cookie（加密存储，仅兼容） |
| GET | `/api/weread/status` | 同步状态 |
| POST | `/api/sync` | 触发同步（异步，前端轮询 `/api/weread/status` 获取进度与错误） |
| GET/POST | `/api/books` | 列出 / 新增（手动）书籍 |
| POST/GET | `/api/checkin` | 打卡 / 打卡状态（含连胜、近 30 天历史） |
| GET | `/api/companion` | 获取温柔提示、阅读进度与今日推荐 |
| GET/POST | `/api/reminders` | 列出 / 新增提醒时间 |
| GET | `/api/reminders/config` | 推送是否配置、订阅模板 ID（不包含 AppSecret） |
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

鉴权：业务接口使用登录得到的 Bearer 会话 token；`/api/login`、`/health` 和共读榜查询无需 token。

## 小程序前端

用微信开发者工具导入 `miniprogram/`，在 `app.js` 把 `globalData.base` 指向后端地址，
`project.config.json` 换成你的 AppID，开发阶段勾选「不校验合法域名」即可联调。

`project.config.json` 当前的 `touristappid` 只是占位值，无法据此完成真实微信登录。
必须使用与后端 `WX_APPID` 相同的小程序 AppID。小程序登录凭证与微信读书 API Key 是两套不同凭证。

开发者工具可用 `http://127.0.0.1:8080`；手机上的 `localhost` 指手机自己，**不能用它访问电脑后端**。
真机正式使用须部署公网 HTTPS 后端，并在微信公众平台配置请求合法域名。

跳转微信读书依赖 `app.json` 的 `navigateToMiniProgramAppIdList`，其中的微信读书 AppID
（`wx8d9bf9c0b4c3f5e1`）请到公众平台核对最新值。

### 手动试用顺序

1. 导入项目、配置同一小程序 AppID 和后端地址，进入首页；如果失败，应看到登录或网络提示，而不是假登录成功。
2. 先不绑定微信读书，去书架手动添加一本书、在书单添加「想读」条目，返回首页查看小书友提示。
3. 点击「我今天读过了」，确认按钮变为已记录，并在阅读报告看到累计记录；重复点击不得增加记录。
4. 在设置页保存官方 API Key，再到书架点同步；完成后查看书名、进度及最近阅读提示。同步失败时应保留旧书架和已知进度。
5. 测试书单增改删、心得发帖/点赞、共读营创建/加入。多人验证需两个真实微信账号。
6. 最后测试跳转微信读书、报告分享图保存到相册、订阅消息推送；这些必须在微信开发者工具/真机上确认。

**当前边界：** 官方同步列表暂只纳入电子书，不把有声专辑/文章收藏计作电子书；
头像选择目前保存的是微信返回的临时路径，尚无持久化上传，不能保证其他设备显示头像；
微信读书跳转 AppID 仍需核实。小书友是轻量静态形象，不是完整宠物养成系统。
首次使用尚无真实 API 数据时，只展示手动书架/书单建议，不生成虚构阅读数据。

### 本地自动检查

```powershell
python test_weread.py
python test_integration.py
node --test test_miniprogram.js
```

同步/提醒用例使用模拟微信响应；HTTP 集成测试启动临时后端、注入测试会话，并在结束后清理独立临时数据库；
前端检查在 Node 中模拟 `wx` 验证页面事件、登录/重登录、同步轮询及提醒授权。
这些检查不替代微信开发者工具的 WXML/WXSS 编译、真实账号 API 联调和手机通知测试。

## 后续演进

- ✅ 阅读可视化报告（`/api/report` + `pages/report`）
- ✅ 共读打卡榜（`/api/leaderboard` + `pages/community`）
- ✅ 心得帖（发帖 + 点赞，`posts`/`post_likes` 表）
- ✅ 共读营（创建/加入/营内榜单与心得，`camps`/`camp_members` 表）
- ✅ canvas 分享图片（报告页生成战绩卡片保存到相册）
- ✅ 书单（想读/在读/读完三段、星级评分、感想，独立可读写，`booklists` 表 + `pages/booklist`）
- ✅ 昵称与头像选择入口（头像临时路径跨设备限制见上文）
- ✅ 官方微信读书 Skills/API Key 同步；旧 Cookie 同步作为兼容选项。
- ✅ 小书友首页：按最近阅读日期推荐回归书目、当前在读书或想读书；提醒文案轻柔且关联推荐书。
- ✅ 同步记录最近阅读日期，并对 7 天以上未读书目给出无压力提示。
