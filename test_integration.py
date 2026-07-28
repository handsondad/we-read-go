"""端到端集成测试：拉起真实后端服务，注入会话后逐一把全部主功能跑通。

覆盖：健康检查、打卡连胜、提醒、手动书目、书单(增改删/跨用户隔离)、
心得帖与点赞、共读营(创建/加入/详情)、资料(昵称头像)、阅读报告、榜单(id 字段)。
"""
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

import json as _json

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(tempfile.gettempdir(), "we_read_it.db")
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"
KEY = "test-key-please-change-32bytes123456"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def inject_user(db_path, openid):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO users(openid) VALUES(?)", (openid,))
    uid = cur.lastrowid
    token = "tok_" + openid
    cur.execute("INSERT INTO sessions(token, user_id) VALUES(?,?)", (token, uid))
    conn.commit()
    conn.close()
    return uid, token


def call(method, path, token="", body=None):
    url = BASE + path
    data = _json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, _json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, _json.loads(e.read().decode())


def main():
    if os.path.exists(DB):
        os.remove(DB)
    global PORT
    PORT = free_port()
    global BASE
    BASE = f"http://127.0.0.1:{PORT}"

    env = dict(os.environ)
    env.update({
        "ADDR": f"127.0.0.1:{PORT}",
        "DB_PATH": DB,
        "ENCRYPT_KEY": KEY,
        "WX_APPID": "testappid",
        "WX_APPSECRET": "testsecret",
        "WX_TEMPLATE_ID": "",
    })
    proc = subprocess.Popen(
        ["python", "backend/server.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        # 等待健康
        for _ in range(50):
            code, _ = call("GET", "/health")
            if code == 200:
                break
            time.sleep(0.2)
        else:
            raise SystemExit("服务未启动")

        # 注入两个用户
        uid1, tok1 = inject_user(DB, "openid_user1")
        uid2, tok2 = inject_user(DB, "openid_user2")

        fails = []

        def check(cond, msg):
            if not cond:
                fails.append(msg)
                print("  [FAIL]", msg)
            else:
                print("  [OK]", msg)

        # 1. 鉴权：无 token -> 401
        code, _ = call("GET", "/api/checkin")
        check(code == 401, "未带 token 应 401")

        # 2. 打卡状态
        code, st = call("GET", "/api/checkin", tok1)
        check(code == 200 and st["todayDone"] is False, "首次打卡状态 todayDone=false")

        # 3. 打卡
        code, r = call("POST", "/api/checkin", tok1)
        check(code == 200 and r["firstTime"] is True, "打卡 firstTime=true")

        # 4. 再次打卡状态
        code, st = call("GET", "/api/checkin", tok1)
        check(code == 200 and st["todayDone"] is True and st["streak"] == 1, "打卡后 streak=1")

        # 5. 提醒
        code, rm = call("POST", "/api/reminders", tok1, {"time": "21:30"})
        check(code == 200 and rm["id"] > 0, "创建提醒成功")
        code, rms = call("GET", "/api/reminders", tok1)
        check(code == 200 and any(x["time"] == "21:30" for x in rms), "提醒列表含新建项")
        code, _ = call("PATCH", f"/api/reminders/{rm['id']}", tok1, {"enabled": False})
        check(code == 200, "提醒启停成功")

        # 6. 手动书目
        code, bk = call("POST", "/api/books", tok1, {"title": "测试书", "author": "甲"})
        check(code == 200 and bk["source"] == "manual" and bk["title"] == "测试书", "手动加书成功")
        code, bks = call("GET", "/api/books", tok1)
        check(code == 200 and len(bks) == 1, "书目列表正确")

        # 7. 书单：增
        code, bl = call("POST", "/api/booklists", tok1,
                        {"title": "书单A", "status": "want", "rating": 5, "note": "好"})
        check(code == 200 and bl["id"] > 0 and bl["rating"] == 5, "书单新增成功")
        bid = bl["id"]
        # 7a. 空书名拦截
        code, _ = call("POST", "/api/booklists", tok1, {"title": ""})
        check(code == 400, "空书名应 400")
        # 7b. 改
        code, _ = call("PATCH", f"/api/booklists/{bid}", tok1, {"status": "finished", "rating": 4})
        check(code == 200, "书单更新成功")
        code, bls = call("GET", "/api/booklists", tok1)
        cur = next(x for x in bls if x["id"] == bid)
        check(cur["status"] == "finished" and cur["rating"] == 4, "书单状态/评分已更新")
        # 7c. 跨用户隔离（user2 删 user1 的书单 -> 404）
        code, _ = call("DELETE", f"/api/booklists/{bid}", tok2)
        check(code == 404, "跨用户删书单应 404")
        # 7d. 同用户删
        code, _ = call("DELETE", f"/api/booklists/{bid}", tok1)
        check(code == 200, "本人删书单成功")
        code, bls = call("GET", "/api/booklists", tok1)
        check(not any(x["id"] == bid for x in bls), "书单已删除")

        # 8. 心得帖
        code, ps = call("POST", "/api/posts", tok1, {"content": "今日心得", "bookTitle": "测试书"})
        check(code == 200 and ps["id"] > 0, "发心得成功")
        pid = ps["id"]
        # 8a. 空内容拦截
        code, _ = call("POST", "/api/posts", tok1, {"content": ""})
        check(code == 400, "空心得应 400")
        # 8b. 点赞
        code, lk = call("POST", f"/api/posts/{pid}/like", tok1)
        check(code == 200 and lk["liked"] is True and lk["likes"] == 1, "点赞成功")
        code, lk = call("POST", f"/api/posts/{pid}/like", tok1)
        check(code == 200 and lk["liked"] is False and lk["likes"] == 0, "再次点击取消赞")
        # 8c. 列表返回字段
        code, pss = call("GET", "/api/posts", tok1)
        post = next(x for x in pss if x["id"] == pid)
        check("name" in post and "avatar" in post and "likes" in post, "心得列表含昵称/头像/点赞")

        # 9. 共读营
        code, cp = call("POST", "/api/camps", tok1, {"name": "共读营1", "bookTitle": "测试书"})
        check(code == 200 and cp["id"] > 0, "创建共读营成功")
        cid = cp["id"]
        code, cps = call("GET", "/api/camps", tok1)
        camp = next(x for x in cps if x["id"] == cid)
        check(camp["joined"] is True, "创建者自动入营")
        # 9a. user2 加入
        code, _ = call("POST", f"/api/camps/{cid}/join", tok2)
        check(code == 200, "user2 加入共读营")
        # 9b. 营详情：成员带 id，含两人均有 id
        code, det = call("GET", f"/api/camps/{cid}", tok1)
        check(code == 200 and "members" in det and "posts" in det, "营详情结构正确")
        member_ids = [m["id"] for m in det["members"]]
        check(len(member_ids) == 2 and all(isinstance(i, int) for i in member_ids),
              "营成员含两条且均带 id（修复 wx:key 冲突）")
        # user2 在营内发心得，应出现在营详情 posts
        code, p2 = call("POST", "/api/posts", tok2, {"content": "营内心得", "campId": cid})
        code, det2 = call("GET", f"/api/camps/{cid}", tok1)
        check(any(x["id"] == p2["id"] for x in det2["posts"]), "营内心得已关联")

        # 10. 资料：昵称头像
        code, _ = call("PATCH", "/api/profile", tok1, {"nickname": "小明", "avatar": "http://x/a.png"})
        check(code == 200, "保存资料成功")
        code, pf = call("GET", "/api/profile", tok1)
        check(pf["nickname"] == "小明" and pf["avatar"] == "http://x/a.png", "资料昵称头像已保存")
        # 仅改昵称不丢头像
        code, _ = call("PATCH", "/api/profile", tok1, {"nickname": "大明"})
        code, pf = call("GET", "/api/profile", tok1)
        check(pf["avatar"] == "http://x/a.png", "仅改昵称不丢头像")

        # 11. 榜单含 id
        code, board = call("GET", "/api/leaderboard")
        check(code == 200 and len(board) >= 1 and "id" in board[0], "榜单含 id 字段")

        # 12. 报告
        code, rep = call("GET", "/api/report", tok1)
        check(code == 200 and "streak" in rep and rep["streak"] == 1, "阅读报告正确")

        if fails:
            print("\n失败 %d 项：" % len(fails))
            for f in fails:
                print(" -", f)
            raise SystemExit(1)
        print("\n全部主功能端到端校验通过 [PASS]")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if os.path.exists(DB):
            os.remove(DB)


if __name__ == "__main__":
    main()
