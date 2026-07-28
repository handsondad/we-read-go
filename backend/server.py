"""HTTP 入口：标准库 http.server 实现，零 Web 框架依赖。

路由表与方法分发由底层 Router 完成，业务处理器调用 services.Services。
提醒调度在后台线程每分钟检查一次，仅在配置了微信凭证时启用。
运行：python backend/server.py
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load as load_config
from db import init as init_db
from crypto import Cipher
from services import Services, ServiceError

cfg = load_config()
conn = init_db(cfg.db_path)
cipher = Cipher(cfg.encrypt_key)
svc = Services(conn, cfg, cipher)


# ---------- 提醒调度线程 ----------


def _scheduler():
    while True:
        time.sleep(60)
        try:
            svc.send_due_reminders()
        except Exception as e:  # 失败不应拖垮调度
            print("reminder push:", e)


if cfg.wx_appid and cfg.wx_appsecret:
    threading.Thread(target=_scheduler, daemon=True).start()


# ---------- 轻量路由 ----------


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, fn):
        rx = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
        self.routes.append((method, re.compile("^" + rx + "$"), fn))

    def match(self, method, path):
        for m, rx, fn in self.routes:
            if m == method:
                mo = rx.match(path)
                if mo:
                    return fn, mo.groupdict()
        return None, None


router = Router()


# ---------- 请求包装 & 鉴权 ----------


class Req:
    def __init__(self, handler):
        self._h = handler
        self.method = ""
        self.path_args = {}

    def json(self):
        length = int(self._h.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        return json.loads(self._h.rfile.read(length).decode("utf-8"))

    @property
    def headers(self):
        return self._h.headers

    def header(self, name):
        return self._h.headers.get(name)

    @property
    def query(self):
        return parse_qs(urlparse(self._h.path).query)


def current_user_id(req: Req) -> int:
    auth = req.header("Authorization") or ""
    token = auth[7:] if auth.startswith("Bearer ") else auth
    if not token:
        q = req.query.get("token")
        if q:
            token = q[0]
    if not token:
        raise ServiceError("未登录或 token 无效", 401)
    return svc.user_id_by_token(token)


# ---------- 业务处理器 ----------


def login(svc, req):
    body = req.json()
    code = body.get("code")
    if not code:
        raise ServiceError("缺少 code", 400)
    token, user = svc.login(code)
    return 200, {"token": token, "user": user}


def save_cookie(svc, req):
    uid = current_user_id(req)
    body = req.json()
    cookie = body.get("cookie")
    if not cookie:
        raise ServiceError("缺少 cookie", 400)
    svc.save_weread_cookie(uid, cookie)
    return 200, {"ok": True}


def weread_status(svc, req):
    uid = current_user_id(req)
    return 200, svc.weread_status(uid)


def sync(svc, req):
    uid = current_user_id(req)
    st = svc.weread_status(uid)
    if not st.get("hasCookie"):
        return 200, {"ok": False, "message": "请先在「我的」页填写微信读书 Cookie"}
    if st.get("syncing"):
        return 200, {"ok": True, "async": True, "running": True}
    # 后台线程执行，避免书架大、逐本请求多时阻塞请求导致超时
    threading.Thread(target=svc.sync_weread, args=(uid,), daemon=True).start()
    return 200, {"ok": True, "async": True}


def books(svc, req):
    uid = current_user_id(req)
    if req.method == "GET":
        return 200, svc.list_books(uid)
    body = req.json()
    if not body.get("title"):
        raise ServiceError("缺少书名", 400)
    created = svc.add_manual_book(uid, body.get("title"), body.get("author", ""), body.get("cover", ""))
    return 200, created


def checkin(svc, req):
    uid = current_user_id(req)
    if req.method == "GET":
        return 200, svc.check_in_status(uid)
    first = svc.check_in(uid)
    return 200, {"ok": True, "firstTime": first}


def reminders(svc, req):
    uid = current_user_id(req)
    if req.method == "GET":
        return 200, svc.list_reminders(uid)
    body = req.json()
    t = body.get("time")
    if not t:
        raise ServiceError("缺少 time", 400)
    return 200, svc.create_reminder(uid, t)


def reminder_patch(svc, req):
    uid = current_user_id(req)
    rid = int(req.path_args["id"])
    body = req.json()
    svc.set_reminder_enabled(rid, uid, bool(body.get("enabled", False)))
    return 200, {"ok": True}


def report(svc, req):
    uid = current_user_id(req)
    return 200, svc.report(uid)


def leaderboard(svc, req):
    return 200, svc.leaderboard(20)


def profile_get(svc, req):
    uid = current_user_id(req)
    return 200, svc.get_profile(uid)


def profile_patch(svc, req):
    uid = current_user_id(req)
    body = req.json()
    svc.update_profile(uid, body.get("nickname", ""), body.get("avatar"))
    return 200, {"ok": True}


def _int_arg(req, name):
    try:
        return int(req.path_args[name])
    except (KeyError, ValueError):
        raise ServiceError("非法的路径参数", 400)


def posts(svc, req):
    uid = current_user_id(req)
    if req.method == "GET":
        camp_id = int((req.query.get("campId") or ["0"])[0] or 0)
        return 200, svc.list_posts(uid, camp_id=camp_id)
    body = req.json()
    created = svc.create_post(
        uid,
        body.get("content", ""),
        body.get("bookTitle", ""),
        int(body.get("campId", 0) or 0),
    )
    return 200, created


def post_like(svc, req):
    uid = current_user_id(req)
    return 200, svc.toggle_like(uid, _int_arg(req, "id"))


def camps(svc, req):
    uid = current_user_id(req)
    if req.method == "GET":
        return 200, svc.list_camps(uid)
    body = req.json()
    return 200, svc.create_camp(uid, body.get("name", ""), body.get("bookTitle", ""))


def camp_join(svc, req):
    uid = current_user_id(req)
    return 200, svc.join_camp(uid, _int_arg(req, "id"))


def camp_detail(svc, req):
    uid = current_user_id(req)
    return 200, svc.camp_detail(uid, _int_arg(req, "id"))


def booklists(svc, req):
    uid = current_user_id(req)
    if req.method == "GET":
        return 200, svc.list_booklists(uid)
    body = req.json()
    created = svc.add_booklist(
        uid,
        body.get("title", ""),
        body.get("author", ""),
        body.get("status", "want"),
        int(body.get("rating", 0) or 0),
        body.get("note", ""),
    )
    return 200, created


def booklist_patch(svc, req):
    uid = current_user_id(req)
    svc.update_booklist(uid, _int_arg(req, "id"), req.json())
    return 200, {"ok": True}


def booklist_delete(svc, req):
    uid = current_user_id(req)
    svc.delete_booklist(uid, _int_arg(req, "id"))
    return 200, {"ok": True}


def health(svc, req):
    return 200, {"status": "ok"}


router.add("POST", "/api/login", login)
router.add("POST", "/api/weread/cookie", save_cookie)
router.add("GET", "/api/weread/status", weread_status)
router.add("POST", "/api/sync", sync)
router.add("GET", "/api/books", books)
router.add("POST", "/api/books", books)
router.add("POST", "/api/checkin", checkin)
router.add("GET", "/api/checkin", checkin)
router.add("GET", "/api/reminders", reminders)
router.add("POST", "/api/reminders", reminders)
router.add("PATCH", "/api/reminders/{id}", reminder_patch)
router.add("GET", "/api/report", report)
router.add("GET", "/api/leaderboard", leaderboard)
router.add("GET", "/api/posts", posts)
router.add("POST", "/api/posts", posts)
router.add("POST", "/api/posts/{id}/like", post_like)
router.add("GET", "/api/camps", camps)
router.add("POST", "/api/camps", camps)
router.add("GET", "/api/camps/{id}", camp_detail)
router.add("POST", "/api/camps/{id}/join", camp_join)
router.add("GET", "/api/booklists", booklists)
router.add("POST", "/api/booklists", booklists)
router.add("PATCH", "/api/booklists/{id}", booklist_patch)
router.add("DELETE", "/api/booklists/{id}", booklist_delete)
router.add("GET", "/api/profile", profile_get)
router.add("PATCH", "/api/profile", profile_patch)
router.add("GET", "/health", health)


# ---------- HTTP 处理器 ----------


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        fn, args = router.match(method, parsed.path)
        if fn is None:
            self._send(404, {"error": "not found"})
            return
        req = Req(self)
        req.method = method
        req.path_args = args or {}
        try:
            status, body = fn(svc, req)
            self._send(status, body)
        except ServiceError as e:
            self._send(e.code, {"error": e.msg})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, *a):
        pass


def main():
    host, _, port = cfg.addr.partition(":")
    port = int(port or 8080)
    print(f"读书管家后端监听 {host}:{port}")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
