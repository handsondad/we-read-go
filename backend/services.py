"""业务逻辑层：登录/会话、微信读书同步、打卡连胜、提醒推送、阅读报告与共读榜。

所有数据库操作都通过 self.lock 串行化，因为 SQLite 连接被后台调度线程复用。
仅依赖标准库 + （间接）cryptography。
"""
import json
import threading
import time
import urllib.parse
import urllib.request

from weread import Client


class ServiceError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.msg = msg
        self.code = code


def _http_json(url: str, data: bytes = None, method: str = "GET") -> dict:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


class Services:
    def __init__(self, conn, cfg, cipher):
        self.conn = conn
        self.cfg = cfg
        self.cipher = cipher
        self.lock = threading.Lock()
        self._token = ""
        self._token_exp = 0.0

    # ---------- 登录与会话 ----------

    def login(self, code: str):
        if not self.cfg.wx_appid or not self.cfg.wx_appsecret:
            raise ServiceError("WX_APPID / WX_APPSECRET 未配置")
        url = (
            "https://api.weixin.qq.com/sns/jscode2session"
            "?appid=%s&secret=%s&js_code=%s&grant_type=authorization_code"
            % (
                urllib.parse.quote(self.cfg.wx_appid),
                urllib.parse.quote(self.cfg.wx_appsecret),
                urllib.parse.quote(code),
            )
        )
        data = _http_json(url)
        if data.get("errcode"):
            raise ServiceError(f"wx login error {data.get('errcode')}: {data.get('errmsg')}")
        openid = data["openid"]
        unionid = data.get("unionid", "")
        user = self._upsert_user(openid, unionid)
        token = self._create_session(user["id"])
        return token, {
            "id": user["id"],
            "nickname": user.get("nickname") or "",
            "avatar": user.get("avatar") or "",
            "createdAt": user.get("created_at") or "",
        }

    def _upsert_user(self, openid: str, unionid: str) -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT id, nickname, avatar, created_at FROM users WHERE openid=?",
                (openid,),
            ).fetchone()
            if row is None:
                cur = self.conn.execute(
                    "INSERT INTO users(openid, unionid) VALUES(?,?)", (openid, unionid)
                )
                self.conn.commit()
                return {
                    "id": cur.lastrowid,
                    "openid": openid,
                    "unionid": unionid,
                    "nickname": "",
                    "avatar": "",
                    "created_at": "",
                }
            return dict(row)

    def _create_session(self, user_id: int) -> str:
        import secrets

        token = secrets.token_hex(24)
        with self.lock:
            self.conn.execute(
                "INSERT INTO sessions(token, user_id) VALUES(?,?)", (token, user_id)
            )
            self.conn.commit()
        return token

    def user_id_by_token(self, token: str) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT user_id FROM sessions WHERE token=?", (token,)
            ).fetchone()
        if row is None:
            raise ServiceError("未登录或 token 无效", 401)
        return row[0]

    # ---------- 微信读书 Cookie ----------

    def save_weread_cookie(self, user_id: int, cookie: str) -> None:
        enc = self.cipher.encrypt(cookie.strip())
        vid = extract_cookie(cookie, "wr_vid")
        with self.lock:
            self.conn.execute(
                """INSERT INTO weread_accounts(user_id, cookie, wr_vid)
                   VALUES(?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     cookie=excluded.cookie, wr_vid=excluded.wr_vid, last_sync_at=NULL""",
                (user_id, enc, vid),
            )
            self.conn.commit()

    def weread_status(self, user_id: int) -> dict:
        with self.lock:
            row = self.conn.execute(
                """SELECT id, wr_vid, last_sync_at,
                          (cookie IS NOT NULL AND cookie<>'') AS has_cookie
                   FROM weread_accounts WHERE user_id=?""",
                (user_id,),
            ).fetchone()
        if row is None:
            return {"id": 0, "userId": user_id, "hasCookie": False}
        info = dict(row)
        out = {
            "id": info["id"],
            "userId": user_id,
            "wrVid": info.get("wr_vid") or "",
            "wrName": info.get("wr_name") or "",
            "hasCookie": bool(info["has_cookie"]),
        }
        if info.get("last_sync_at"):
            out["lastSyncAt"] = info["last_sync_at"]
        return out

    def _weread_cookie(self, user_id: int) -> str:
        with self.lock:
            row = self.conn.execute(
                "SELECT cookie FROM weread_accounts WHERE user_id=?", (user_id,)
            ).fetchone()
        if row is None or not row["cookie"]:
            raise ServiceError("尚未绑定微信读书 Cookie")
        return self.cipher.decrypt(row["cookie"])

    # ---------- 同步微信读书数据 ----------

    def sync_weread(self, user_id: int) -> None:
        cookie = self._weread_cookie(user_id)
        client = Client(cookie, self.cfg.weread_ua)

        books = client.shelf()
        try:
            notes = client.notebook()
        except Exception:
            notes = {}

        for b in books:
            book_id = b.get("bookId")
            if not book_id:
                continue
            progress = int(b.get("progress", 0) or 0)
            if not progress:
                try:
                    progress = client.read_info(book_id)
                except Exception:
                    progress = 0
            with self.lock:
                self.conn.execute(
                    """INSERT INTO books(user_id, book_id, title, author, cover, source, status, progress, added_at)
                       VALUES(?,?,?,?,?, 'weread', ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id, book_id) DO UPDATE SET
                         title=excluded.title, author=excluded.author, cover=excluded.cover,
                         status=excluded.status, progress=excluded.progress""",
                    (
                        user_id,
                        book_id,
                        b.get("title", ""),
                        b.get("author", ""),
                        b.get("cover", ""),
                        b.get("status", "reading"),
                        progress,
                    ),
                )
                self.conn.commit()
            _ = notes  # 笔记数量可在此扩展存储

        try:
            raw = client.read_data()
            with self.lock:
                self.conn.execute(
                    "INSERT INTO user_stats(user_id, date, payload) VALUES(?,?,?)",
                    (user_id, time.strftime("%Y-%m-%d"), raw.decode("utf-8", "ignore")),
                )
                self.conn.commit()
        except Exception:
            pass

        with self.lock:
            self.conn.execute(
                "UPDATE weread_accounts SET last_sync_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (user_id,),
            )
            self.conn.commit()

    # ---------- 书籍 ----------

    def list_books(self, user_id: int) -> list:
        with self.lock:
            rows = self.conn.execute(
                """SELECT id, book_id, title, author, cover, source, status, progress, added_at
                   FROM books WHERE user_id=? ORDER BY added_at DESC""",
                (user_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "userId": user_id,
                "bookId": r["book_id"] or "",
                "title": r["title"],
                "author": r["author"] or "",
                "cover": r["cover"] or "",
                "source": r["source"],
                "status": r["status"],
                "progress": r["progress"],
                "addedAt": r["added_at"] or "",
            }
            for r in rows
        ]

    def add_manual_book(self, user_id: int, title: str, author: str, cover: str) -> dict:
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO books(user_id, title, author, cover, source, status, progress, added_at)
                   VALUES(?,?,?,?, 'manual', 'reading', 0, CURRENT_TIMESTAMP)""",
                (user_id, title, author or "", cover or ""),
            )
            self.conn.commit()
            added_at = self.conn.execute(
                "SELECT added_at FROM books WHERE id=?", (cur.lastrowid,)
            ).fetchone()["added_at"]
        return {
            "id": cur.lastrowid,
            "userId": user_id,
            "title": title,
            "author": author or "",
            "cover": cover or "",
            "source": "manual",
            "status": "reading",
            "progress": 0,
            "addedAt": added_at or "",
        }

    # ---------- 打卡 ----------

    def check_in(self, user_id: int) -> bool:
        today = time.strftime("%Y-%m-%d")
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO checkins(user_id, date) VALUES(?,?)", (user_id, today)
            )
            self.conn.commit()
            return cur.rowcount > 0

    def check_in_status(self, user_id: int) -> dict:
        today = time.strftime("%Y-%m-%d")
        with self.lock:
            cnt = self.conn.execute(
                "SELECT COUNT(*) FROM checkins WHERE user_id=? AND date=?",
                (user_id, today),
            ).fetchone()[0]
            rows = self.conn.execute(
                "SELECT date FROM checkins WHERE user_id=? ORDER BY date DESC LIMIT 30",
                (user_id,),
            ).fetchall()
        history = [r["date"] for r in rows]
        return {"todayDone": cnt > 0, "streak": self._streak(user_id), "history": history}

    def _streak(self, user_id: int) -> int:
        with self.lock:
            rows = self.conn.execute(
                "SELECT date FROM checkins WHERE user_id=? ORDER BY date DESC", (user_id,)
            ).fetchall()
        dates = {r["date"] for r in rows}
        streak = 0
        d = time.strftime("%Y-%m-%d")
        while streak <= 3650:
            if d in dates:
                streak += 1
                d = _shift_day(d, -1)
            else:
                break
        return streak

    # ---------- 提醒 ----------

    def create_reminder(self, user_id: int, t: str) -> dict:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO reminders(user_id, time) VALUES(?,?)", (user_id, t)
            )
            self.conn.commit()
            created_at = self.conn.execute(
                "SELECT created_at FROM reminders WHERE id=?", (cur.lastrowid,)
            ).fetchone()["created_at"]
        return {
            "id": cur.lastrowid,
            "userId": user_id,
            "time": t,
            "enabled": True,
            "createdAt": created_at or "",
        }

    def list_reminders(self, user_id: int) -> list:
        with self.lock:
            rows = self.conn.execute(
                """SELECT id, time, enabled, last_sent_at, created_at
                   FROM reminders WHERE user_id=? ORDER BY time""",
                (user_id,),
            ).fetchall()
        out = []
        for r in rows:
            item = {
                "id": r["id"],
                "userId": user_id,
                "time": r["time"],
                "enabled": bool(r["enabled"]),
                "createdAt": r["created_at"] or "",
            }
            if r["last_sent_at"]:
                item["lastSentAt"] = r["last_sent_at"]
            out.append(item)
        return out

    def set_reminder_enabled(self, rid: int, user_id: int, enabled: bool) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE reminders SET enabled=? WHERE id=? AND user_id=?",
                (1 if enabled else 0, rid, user_id),
            )
            self.conn.commit()

    # ---------- 微信订阅消息推送 ----------

    def _access_token(self) -> str:
        with self.lock:
            if self._token and time.time() < self._token_exp:
                return self._token
        data = _http_json(
            "https://api.weixin.qq.com/cgi-bin/token"
            "?grant_type=client_credential&appid=%s&secret=%s"
            % (
                urllib.parse.quote(self.cfg.wx_appid),
                urllib.parse.quote(self.cfg.wx_appsecret),
            )
        )
        if data.get("errcode"):
            raise ServiceError(f"get access_token error {data.get('errcode')}: {data.get('errmsg')}")
        with self.lock:
            self._token = data["access_token"]
            self._token_exp = time.time() + 55 * 60
        return self._token

    def send_due_reminders(self) -> None:
        if not (self.cfg.wx_appid and self.cfg.wx_appsecret and self.cfg.wx_template_id):
            return
        now = time.strftime("%H:%M")
        today = time.strftime("%Y-%m-%d")
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, user_id, last_sent_at FROM reminders WHERE enabled=1 AND time=?",
                (now,),
            ).fetchall()
        for r in rows:
            if r["last_sent_at"] == today:
                continue
            with self.lock:
                openid_row = self.conn.execute(
                    "SELECT openid FROM users WHERE id=?", (r["user_id"],)
                ).fetchone()
            if not openid_row:
                continue
            self._send_subscribe(openid_row["openid"], now)
            with self.lock:
                self.conn.execute(
                    "UPDATE reminders SET last_sent_at=? WHERE id=?", (today, r["id"])
                )
                self.conn.commit()

    def _send_subscribe(self, openid: str, when: str) -> None:
        token = self._access_token()
        payload = {
            "touser": openid,
            "template_id": self.cfg.wx_template_id,
            "page": "pages/index/index",
            "data": {
                "thing1": {"value": "该读书啦，保持连续打卡"},
                "time2": {"value": when},
            },
        }
        data = _http_json(
            "https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token="
            + urllib.parse.quote(token),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        if data.get("errcode"):
            raise ServiceError(
                f"subscribe send error {data.get('errcode')}: {data.get('errmsg')}"
            )

    # ---------- 阅读报告 & 社区 ----------

    def report(self, user_id: int) -> dict:
        streak = self._streak(user_id)
        with self.lock:
            total = self.conn.execute(
                "SELECT COUNT(*) FROM checkins WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            since = _shift_day(time.strftime("%Y-%m-%d"), -6)
            week = self.conn.execute(
                "SELECT COUNT(*) FROM checkins WHERE user_id=? AND date>=?",
                (user_id, since),
            ).fetchone()[0]
            reading = self.conn.execute(
                "SELECT COUNT(*) FROM books WHERE user_id=? AND status='reading'",
                (user_id,),
            ).fetchone()[0]
            finished = self.conn.execute(
                "SELECT COUNT(*) FROM books WHERE user_id=? AND status='finished'",
                (user_id,),
            ).fetchone()[0]
            stat = self.conn.execute(
                "SELECT payload FROM user_stats WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        seconds = extract_reading_seconds(stat["payload"]) if stat else 0
        return {
            "streak": streak,
            "totalCheckins": total,
            "weekCheckins": week,
            "booksReading": reading,
            "booksFinished": finished,
            "readingSeconds": seconds,
            "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def leaderboard(self, limit: int = 20) -> list:
        with self.lock:
            users = self.conn.execute(
                "SELECT id, openid, nickname FROM users"
            ).fetchall()
            totals_rows = self.conn.execute(
                "SELECT user_id, COUNT(*) AS c FROM checkins GROUP BY user_id"
            ).fetchall()
        totals = {r["user_id"]: r["c"] for r in totals_rows}
        board = []
        for u in users:
            name = u["nickname"] or mask_openid(u["openid"])
            board.append(
                {
                    "name": name,
                    "streak": self._streak(u["id"]),
                    "total": totals.get(u["id"], 0),
                }
            )
        board.sort(key=lambda x: x["total"], reverse=True)
        return board[:limit] if limit > 0 else board

    def get_profile(self, user_id: int) -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT nickname FROM users WHERE id=?", (user_id,)
            ).fetchone()
        return {"nickname": row["nickname"] if row else ""}

    def update_profile(self, user_id: int, nickname: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE users SET nickname=? WHERE id=?", (nickname, user_id)
            )
            self.conn.commit()


# ---------- 辅助函数 ----------


def extract_cookie(cookie: str, name: str) -> str:
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1 :]
    return ""


def _shift_day(date_str: str, delta: int) -> str:
    t = time.strptime(date_str, "%Y-%m-%d")
    return time.strftime("%Y-%m-%d", time.localtime(time.mktime(t) + delta * 86400))


def extract_reading_seconds(payload: str) -> int:
    try:
        m = json.loads(payload)
    except Exception:
        return 0
    if not isinstance(m, dict):
        return 0
    for key in ("readingTime", "readTime", "totalReadTime", "reading_time", "allReadingTime"):
        if key in m:
            try:
                return int(m[key])
            except Exception:
                return 0
    return 0


def mask_openid(openid: str) -> str:
    if len(openid) <= 4:
        return "书友" + openid
    return "书友" + openid[-4:]
