"""微信读书同步稳定性单元测试。

不依赖真实网络：通过替换 weread._opener 注入各类响应，验证
重试退避、Cookie 失效识别、结构化结果与错误落库等稳定性逻辑。
运行：python test_weread.py
"""
import os
import json
import sqlite3
import sys
import time
import urllib.error
import contextlib
from unittest.mock import patch
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import weread
from weread import WereadError
import db as dbmod
from crypto import Cipher
from config import Config
from services import Services, ServiceError

WEREAD_UA = "Mozilla/5.0 (test)"


class FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def open(self, req, timeout=None):
        self.calls.append(req.full_url)
        return self.script(req.full_url)


def build_svc():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(dbmod.SCHEMA)
    dbmod._migrate(conn)
    cipher = Cipher("test-encrypt-key")
    cfg = Config(
        addr="", db_path="", encrypt_key="", wx_appid="", wx_appsecret="",
        wx_template_id="", weread_ua=WEREAD_UA,
    )
    svc = Services(conn, cfg, cipher)
    u = svc._upsert_user("openid_test", "")
    return svc, conn, u["id"]


@contextlib.contextmanager
def with_opener(script):
    orig = weread._opener
    weread._opener = FakeOpener(script)
    orig_sleep = weread.time.sleep
    weread.time.sleep = lambda *a, **k: None  # 加速测试
    try:
        yield weread._opener
    finally:
        weread._opener = orig
        weread.time.sleep = orig_sleep


def shelf_current():
    return '{"books":[{"bookId":"b1","title":"书一","author":"甲","cover":"c1","progress":80}]}'


def shelf_finish():
    return '{"finishReadBooks":[{"bookId":"b2","title":"书二","progress":100}]}'


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)
        print("  [FAIL]", msg)
    else:
        print("  [OK]", msg)


def test_valid():
    print("[用例] 正常同步：书架落库 + 进度回退 + 错误清空")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=123; wr_name=tester")
    captured = {}

    def script(url):
        if "/shelf/current" in url:
            return FakeResp(200, shelf_current())
        if "/shelf/finish" in url:
            return FakeResp(200, shelf_finish())
        if "/book/readinfo" in url:
            captured["readinfo"] = url
            return FakeResp(200, '{"readingProgress":42}')
        if "/readdata" in url:
            return FakeResp(200, '{"readingTime":3600}')
        return FakeResp(200, '{}')

    with with_opener(script):
        res = svc.sync_weread(uid)
    check(res["ok"] is True, "返回 ok=True", fails)
    check(res["synced"] == 2, "同步 2 本书 (got %s)" % res["synced"], fails)
    rows = conn.execute("SELECT book_id, progress FROM books WHERE user_id=?", (uid,)).fetchall()
    ids = {r["book_id"]: r["progress"] for r in rows}
    check(ids.get("b1") == 80, "b1 进度保留 80", fails)
    check(ids.get("b2") == 100, "b2 进度保留 100", fails)
    check("readinfo" not in captured, "有 progress 时不调用 readinfo", fails)
    st = svc.weread_status(uid)
    check(bool(st.get("lastSyncAt")), "lastSyncAt 已写入", fails)
    check("lastSyncError" not in st, "成功时 lastSyncError 为空", fails)
    check(st.get("syncing") is False, "同步结束后 syncing=False", fails)
    return fails


def test_progress_fallback():
    print("[用例] 书架无 progress 时回退调用 readinfo")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=1")
    got = {}

    def script(url):
        if "/shelf/current" in url:
            return FakeResp(200, '{"books":[{"bookId":"b1","title":"T","progress":0}]}')
        if "/shelf/finish" in url:
            return FakeResp(200, '{"finishReadBooks":[]}')
        if "/book/readinfo" in url:
            got["bid"] = url.split("bookId=")[1]
            return FakeResp(200, '{"readingProgress":42}')
        return FakeResp(200, '{}')

    with with_opener(script):
        svc.sync_weread(uid)
    row = conn.execute("SELECT progress FROM books WHERE user_id=? AND book_id='b1'", (uid,)).fetchone()
    check(row["progress"] == 42, "readinfo 回退写入进度 42 (got %s)" % (row["progress"] if row else None), fails)
    check(got.get("bid") == "b1", "readinfo 请求了正确的 bookId", fails)
    return fails


def test_cookie_invalid_redirect():
    print("[用例] Cookie 失效被 302 跳转识别")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=1")

    def script(url):
        return FakeResp(302, "<html>login</html>")

    with with_opener(script):
        res = svc.sync_weread(uid)
    check(res["ok"] is False, "ok=False", fails)
    check(res["cookieInvalid"] is True, "cookieInvalid=True", fails)
    check("失效" in res["message"], "message 提示失效", fails)
    st = svc.weread_status(uid)
    check("lastSyncError" in st, "lastSyncError 已落库", fails)
    check(not st.get("lastSyncAt"), "失败不更新 lastSyncAt", fails)
    check(st.get("syncing") is False, "结束后 syncing=False", fails)
    return fails


def test_cookie_invalid_html():
    print("[用例] Cookie 失效返回登录页 HTML 被识别")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=1")

    def script(url):
        return FakeResp(200, "<!doctype html><html>请登录</html>")

    with with_opener(script):
        res = svc.sync_weread(uid)
    check(res["ok"] is False and res["cookieInvalid"] is True, "ok=False 且 cookieInvalid=True", fails)
    return fails


def test_cookie_invalid_errcode():
    print("[用例] 错误码 JSON 被识别为 Cookie 失效")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=1")

    def script(url):
        return FakeResp(200, '{"errcode":-2011,"errmsg":"登录失效，请重新登录"}')

    with with_opener(script):
        res = svc.sync_weread(uid)
    check(res["ok"] is False and res["cookieInvalid"] is True, "ok=False 且 cookieInvalid=True", fails)
    check("登录失效" in res["message"], "message 透传 errmsg", fails)
    return fails


def test_retry_transient():
    print("[用例] 瞬时超时自动重试后成功")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=1")
    state = {"n": 0}

    def script(url):
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.URLError("timed out")
        if "/shelf/current" in url:
            return FakeResp(200, shelf_current())
        if "/shelf/finish" in url:
            return FakeResp(200, shelf_finish())
        if "/book/readinfo" in url:
            return FakeResp(200, '{"readingProgress":1}')
        return FakeResp(200, '{}')

    opener = None
    with with_opener(script) as op:
        opener = op
        res = svc.sync_weread(uid)
    check(res["ok"] is True, "重试后 ok=True", fails)
    check(len(opener.calls) >= 2, "发生了重试 (calls=%d)" % len(opener.calls), fails)
    return fails


def test_5xx_exhausted():
    print("[用例] 5xx 重试耗尽后结构化失败（非 Cookie 失效）")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_cookie(uid, "wr_vid=1")

    def script(url):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)

    with with_opener(script):
        res = svc.sync_weread(uid)
    check(res["ok"] is False, "ok=False", fails)
    check(res["cookieInvalid"] is False, "5xx 不误判为 Cookie 失效", fails)
    check("503" in res["message"], "message 含 HTTP 503", fails)
    return fails


def test_no_cookie():
    print("[用例] 未绑定 Cookie 时不崩溃")
    fails = []
    svc, conn, uid = build_svc()
    res = svc.sync_weread(uid)
    check(res["ok"] is False, "ok=False", fails)
    check("Cookie" in res["message"], "message 提示未绑定 Cookie", fails)
    return fails


def test_official_api_key_sync():
    print("[用例] 官方 API Key 同步书架、进度与最近阅读日期")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_api_key(uid, "wrk-test-key")
    captured = []
    update_time = int(time.time()) - 86400

    def fake_open(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        captured.append((req, body))
        if body["api_name"] == "/shelf/sync":
            payload = {"books": [{
                "bookId": "official-1", "title": "官方书", "author": "作者",
                "cover": "cover", "finishReading": 0, "readUpdateTime": update_time,
            }]}
        elif body["api_name"] == "/book/getprogress":
            payload = {"book": {"progress": 37, "updateTime": update_time}}
        else:
            payload = {"totalReadTime": 120}
        return FakeResp(200, json.dumps(payload))

    with patch.object(weread.urllib.request, "urlopen", fake_open):
        result = svc.sync_weread(uid)

    row = conn.execute(
        "SELECT progress, status, last_read_at FROM books WHERE user_id=? AND book_id='official-1'",
        (uid,),
    ).fetchone()
    status = svc.weread_status(uid)
    check(result["ok"] is True and result["synced"] == 1, "官方 API 同步成功", fails)
    check(row["progress"] == 37 and row["status"] == "reading", "官方进度写入 37%", fails)
    check(row["last_read_at"] == datetime.datetime.fromtimestamp(update_time).strftime("%Y-%m-%d"),
          "最近阅读日期已保存", fails)
    check(status["hasApiKey"] is True and status["hasCookie"] is False, "仅返回凭证是否已配置", fails)
    check(all(req.get_header("Authorization") == "Bearer wrk-test-key" for req, _ in captured),
          "API Key 使用 Authorization Header", fails)
    check(all(body["skill_version"] == weread.SKILL_VERSION for _, body in captured),
          "每个官方调用都带 skill_version", fails)
    stats_body = next(body for _, body in captured if body["api_name"] == "/readdata/detail")
    check(stats_body["mode"] == "overall" and svc.report(uid)["readingSeconds"] == 120,
          "累计阅读报告使用 overall 统计且时长单位为秒", fails)
    encrypted = conn.execute(
        "SELECT api_key FROM weread_accounts WHERE user_id=?", (uid,)
    ).fetchone()["api_key"]
    check("wrk-test-key" not in encrypted, "API Key 加密后入库", fails)
    return fails


def test_companion_recommendation():
    print("[用例] 小书友优先推荐久未阅读且无责备语气")
    fails = []
    svc, conn, uid = build_svc()
    old_date = (datetime.date.today() - datetime.timedelta(days=12)).isoformat()
    conn.execute(
        """INSERT INTO books(user_id, book_id, title, source, status, progress, last_read_at)
           VALUES(?,?,?,?,?,?,?)""",
        (uid, "old-book", "搁置的书", "weread", "reading", 24, old_date),
    )
    conn.commit()
    result = svc.companion(uid)
    rec = result["recommendation"]
    check(result["state"] == "returning", "识别久未阅读状态", fails)
    check(rec["bookId"] == "old-book" and rec["daysSinceRead"] == 12, "优先推荐久未阅读书并带原因", fails)
    check("不用补进度" in result["message"] and "打卡" not in result["message"], "回归提示不内疚、不施压", fails)
    svc.check_in(uid)
    checked_in = svc.companion(uid)
    check("休息一下也可以" in checked_in["message"], "完成今日阅读后提示休息，不继续催读", fails)
    return fails


def test_existing_database_migration():
    print("[用例] 旧数据库自动补充 API Key 和最近阅读字段")
    fails = []
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE weread_accounts (
           id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, cookie TEXT, wr_vid TEXT,
           wr_name TEXT, last_sync_at DATETIME, last_sync_error TEXT, syncing INTEGER,
           created_at DATETIME)"""
    )
    conn.execute(
        """CREATE TABLE books (
           id INTEGER PRIMARY KEY, user_id INTEGER, book_id TEXT, title TEXT,
           author TEXT, cover TEXT, source TEXT, status TEXT, progress INTEGER,
           added_at DATETIME, UNIQUE(user_id, book_id))"""
    )
    dbmod._migrate(conn)
    account_cols = {row[1] for row in conn.execute("PRAGMA table_info(weread_accounts)")}
    book_cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    check("api_key" in account_cols, "旧账号表新增 api_key", fails)
    check("last_read_at" in book_cols, "旧书籍表新增 last_read_at", fails)
    return fails


def test_official_failure_preserves_progress():
    print("[用例] 官方进度失败保留旧进度，升级提示中止同步")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_api_key(uid, "wrk-test")
    conn.execute(
        """INSERT INTO books(user_id, book_id, title, status, progress, last_read_at)
           VALUES(?, 'b1', '旧书名', 'reading', 67, '2026-01-02')""", (uid,)
    )
    conn.commit()
    shelf = [{"bookId": "b1", "title": "新书名", "status": "reading"}]
    with patch.object(weread.ApiKeyClient, "shelf", return_value=shelf), \
         patch.object(weread.ApiKeyClient, "read_progress", side_effect=WereadError("临时不可用")), \
         patch.object(weread.ApiKeyClient, "read_data", return_value={"totalReadTime": 500}):
        result = svc.sync_weread(uid)
    book = svc.list_books(uid)[0]
    check(result["ok"] and result["warnings"], "部分失败明确返回警告", fails)
    check(book["progress"] == 67 and book["lastReadAt"] == "2026-01-02",
          "失败不将旧进度归零或清空阅读日期", fails)

    with patch.object(weread.ApiKeyClient, "shelf", return_value=shelf), \
         patch.object(weread.ApiKeyClient, "read_progress",
                      side_effect=WereadError("必须升级", upgrade_required=True)), \
         patch.object(weread.ApiKeyClient, "read_data") as stats:
        result = svc.sync_weread(uid)
    check(not result["ok"] and "升级" in result["message"], "升级要求不被可选进度吞掉", fails)
    check(not stats.called, "收到升级要求后不再调用其他接口", fails)

    with patch.object(weread.ApiKeyClient, "shelf", return_value=[
        {"bookId": "new-book", "title": "不应落库", "status": "reading"}
    ]), patch.object(weread.ApiKeyClient, "read_progress", return_value={"progress": 30}), \
         patch.object(weread.ApiKeyClient, "read_data",
                      side_effect=WereadError("统计要求升级", upgrade_required=True)):
        result = svc.sync_weread(uid)
    check(not result["ok"] and not any(
        book["bookId"] == "new-book" for book in svc.list_books(uid)
    ), "同步末尾遇到升级指令也不部分写入书架", fails)

    with patch.object(weread.ApiKeyClient, "shelf", return_value=[
        {"bookId": "b2", "title": "已读完", "status": "finished"}
    ]), patch.object(weread.ApiKeyClient, "read_data", return_value={}):
        result = svc.sync_weread(uid)
    finished = next(book for book in svc.list_books(uid) if book["bookId"] == "b2")
    check(finished["progress"] == 100, "已读完书籍显示 100% 而不是 0%", fails)
    return fails


def test_sync_reservation():
    print("[用例] 同步并发与凭证保护")
    fails = []
    svc, conn, uid = build_svc()
    svc.save_weread_api_key(uid, "wrk-test")
    check(svc.reserve_sync(uid) is True, "首次同步预占成功", fails)
    check(svc.reserve_sync(uid) is False, "重复点击不重复启动同步", fails)
    try:
        svc.save_weread_api_key(uid, "wrk-replacement")
        check(False, "同步过程中禁止换凭证", fails)
    except ServiceError as e:
        check(e.code == 409, "同步过程中禁止换凭证", fails)
    return fails


def test_official_gateway_errors():
    print("[用例] 官方接口错误、升级指令与回包验证")
    fails = []
    client = weread.ApiKeyClient("wrk-test")
    with patch.object(weread.urllib.request, "urlopen", side_effect=urllib.error.HTTPError(
        weread.GATEWAY, 401, "Unauthorized", {}, None
    )):
        try:
            client.shelf()
            check(False, "401 明确识别 API Key 无效", fails)
        except WereadError as e:
            check(e.api_key_invalid and not e.cookie_invalid, "401 明确识别 API Key 无效", fails)
    with patch.object(weread.urllib.request, "urlopen", return_value=FakeResp(
        200, '{"upgrade_info":{"message":"请升级版本"}}'
    )):
        try:
            client.shelf()
            check(False, "升级指令必须中止", fails)
        except WereadError as e:
            check(e.upgrade_required, "升级指令必须中止", fails)
    with patch.object(weread.urllib.request, "urlopen", return_value=FakeResp(200, '{}')):
        try:
            client.read_progress("b1")
            check(False, "缺失进度不能当作零进度", fails)
        except WereadError:
            check(True, "缺失进度不能当作零进度", fails)
    try:
        Cipher("")
        check(False, "拒绝使用空加密密钥启动", fails)
    except RuntimeError as e:
        check("ENCRYPT_KEY" in str(e), "拒绝使用空加密密钥启动", fails)
    return fails


def test_reminder_delivery():
    print("[用例] 提醒限频、已读免打扰、单用户失败隔离")
    fails = []
    svc, conn, uid = build_svc()
    svc.cfg.wx_appid = "test"
    svc.cfg.wx_appsecret = "test"
    svc.cfg.wx_template_id = "template"
    now = time.strftime("%H:%M")
    svc.create_reminder(uid, now)
    svc.create_reminder(uid, now)
    with patch.object(svc, "_send_subscribe") as send:
        svc.send_due_reminders()
        svc.send_due_reminders()
    check(send.call_count == 1, "同用户多个提醒当天最多发送一次", fails)
    uid2 = svc._upsert_user("reader", "")["id"]
    svc.create_reminder(uid2, now)
    svc.check_in(uid2)
    with patch.object(svc, "_send_subscribe") as send:
        svc.send_due_reminders()
    check(send.call_count == 0, "今日已读不再催读", fails)
    uid3 = svc._upsert_user("denied", "")["id"]
    uid4 = svc._upsert_user("accepted", "")["id"]
    svc.create_reminder(uid3, now)
    svc.create_reminder(uid4, now)
    with patch.object(svc, "_send_subscribe", side_effect=[ServiceError("未授权"), None]) as send:
        svc.send_due_reminders()
    check(send.call_count == 2, "一个用户未授权不阻断其他用户提醒", fails)
    check(conn.execute("SELECT last_sent_at FROM reminders WHERE user_id=?", (uid4,)).fetchone()[0],
          "成功发送才记录日期", fails)
    return fails


def main():
    all_fails = []
    tests = (
        test_valid,
        test_progress_fallback,
        test_cookie_invalid_redirect,
        test_cookie_invalid_html,
        test_cookie_invalid_errcode,
        test_retry_transient,
        test_5xx_exhausted,
        test_no_cookie,
        test_official_api_key_sync,
        test_companion_recommendation,
        test_existing_database_migration,
        test_official_failure_preserves_progress,
        test_sync_reservation,
        test_reminder_delivery,
        test_official_gateway_errors,
    )
    for t in tests:
        all_fails += t()
    if all_fails:
        print("\n微信读书同步稳定性测试失败 [FAIL]:")
        for f in all_fails:
            print(" -", f)
        sys.exit(1)
    print("\n微信读书同步稳定性测试全部通过 [PASS] (%d 项)" % len(tests))


if __name__ == "__main__":
    main()
