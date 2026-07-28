import os

os.environ["DB_PATH"] = "test_smoke.db"

import server
from services import ServiceError

# 1) 路由注册检查
expected = [
    ("POST", "/api/login"),
    ("POST", "/api/weread/cookie"),
    ("GET", "/api/weread/status"),
    ("POST", "/api/sync"),
    ("GET", "/api/books"),
    ("POST", "/api/books"),
    ("POST", "/api/checkin"),
    ("GET", "/api/checkin"),
    ("GET", "/api/reminders"),
    ("POST", "/api/reminders"),
    ("PATCH", "/api/reminders/1"),
    ("GET", "/api/report"),
    ("GET", "/api/leaderboard"),
    ("GET", "/api/profile"),
    ("PATCH", "/api/profile"),
    ("GET", "/health"),
]
for method, path in expected:
    fn, args = server.router.match(method, path)
    assert fn is not None, f"route not registered: {method} {path}"
    if "{id}" in path:
        assert args.get("id") is not None, f"path arg missing: {path}"
print("routes OK")

# 2) 未配置微信凭证时登录应报错
try:
    server.svc.login("dummy-code")
    print("login: FAIL (expected error)")
except ServiceError as e:
    print("login no-wx ->", e.code, e.msg)

# 3) 直接造一个用户与会话，验证打卡/报告/榜单/资料
import sqlite3

svc = server.svc
with svc.lock:
    svc.conn.execute("INSERT INTO users(openid, nickname) VALUES(?,?)", ("openid_test", "小明"))
    svc.conn.commit()
    uid = svc.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    svc.conn.execute("INSERT INTO sessions(token, user_id) VALUES(?,?)", ("tok_test", uid))
    svc.conn.commit()

print("check_in first ->", svc.check_in(uid))
print("check_in again ->", svc.check_in(uid))
st = svc.check_in_status(uid)
print("check_in_status ->", st)
svc.add_manual_book(uid, "人类简史", "尤瓦尔", "")
rep = svc.report(uid)
print("report ->", rep)
lb = svc.leaderboard(20)
print("leaderboard ->", lb)
svc.update_profile(uid, "小明同学")
print("profile ->", svc.get_profile(uid))

print("SMOKE_DONE")
