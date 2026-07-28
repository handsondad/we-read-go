"""微信读书同步稳定性单元测试。

不依赖真实网络：通过替换 weread._opener 注入各类响应，验证
重试退避、Cookie 失效识别、结构化结果与错误落库等稳定性逻辑。
运行：python test_weread.py
"""
import os
import sqlite3
import sys
import urllib.error
import contextlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import weread
from weread import WereadError
import db as dbmod
from crypto import Cipher
from config import Config
from services import Services

WEREAD_UA = "Mozilla/5.0 (test)"


class FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body


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


def main():
    all_fails = []
    for t in (
        test_valid,
        test_progress_fallback,
        test_cookie_invalid_redirect,
        test_cookie_invalid_html,
        test_cookie_invalid_errcode,
        test_retry_transient,
        test_5xx_exhausted,
        test_no_cookie,
    ):
        all_fails += t()
    if all_fails:
        print("\n微信读书同步稳定性测试失败 [FAIL]:")
        for f in all_fails:
            print(" -", f)
        sys.exit(1)
    print("\n微信读书同步稳定性测试全部通过 [PASS] (%d 项)" % 8)


if __name__ == "__main__":
    main()
