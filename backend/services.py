"""业务逻辑层：登录/会话、微信读书同步、打卡连胜、提醒推送、阅读报告与共读榜。

所有数据库操作都通过 self.lock 串行化，因为 SQLite 连接被后台调度线程复用。
仅依赖标准库 + （间接）cryptography。
"""
import json
import threading
import time
import urllib.parse
import urllib.request

from weread import Client, WereadError


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
                     cookie=excluded.cookie, wr_vid=excluded.wr_vid,
                     last_sync_at=NULL, last_sync_error=NULL, syncing=0""",
                (user_id, enc, vid),
            )
            self.conn.commit()

    def weread_status(self, user_id: int) -> dict:
        with self.lock:
            row = self.conn.execute(
                """SELECT id, wr_vid, last_sync_at, last_sync_error, syncing,
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
            "syncing": bool(info.get("syncing")),
        }
        if info.get("last_sync_at"):
            out["lastSyncAt"] = info["last_sync_at"]
        if info.get("last_sync_error"):
            out["lastSyncError"] = info["last_sync_error"]
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

    def sync_weread(self, user_id: int) -> dict:
        """同步微信读书书架与阅读统计。

        设计目标：永不向上层抛出未捕获异常（保证核心打卡/提醒不受影响），
        返回结构化结果 {ok, synced, message, cookieInvalid}，并落库 last_sync_at /
        last_sync_error / syncing 供前端轮询展示。失败时仅记录错误，不污染已同步的数据。
        """
        with self.lock:
            self.conn.execute(
                "UPDATE weread_accounts SET syncing=1 WHERE user_id=?", (user_id,)
            )
            self.conn.commit()

        result = {"ok": True, "synced": 0, "message": "同步完成", "cookieInvalid": False}
        try:
            cookie = self._weread_cookie(user_id)
            client = Client(cookie, self.cfg.weread_ua)

            books = client.shelf()
            synced = 0
            for b in books:
                book_id = b.get("bookId")
                if not book_id:
                    continue
                progress = int(b.get("progress", 0) or 0)
                if not progress:
                    progress = client.read_info(book_id)
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
                synced += 1

            try:
                raw = client.read_data()
                with self.lock:
                    self.conn.execute(
                        "INSERT INTO user_stats(user_id, date, payload) VALUES(?,?,?)",
                        (user_id, time.strftime("%Y-%m-%d"), raw.decode("utf-8", "ignore")),
                    )
                    self.conn.commit()
            except Exception:
                pass  # 阅读统计为可选项，失败不影响书架同步结果

            result["synced"] = synced
            with self.lock:
                self.conn.execute(
                    "UPDATE weread_accounts SET last_sync_at=CURRENT_TIMESTAMP, last_sync_error=NULL "
                    "WHERE user_id=?",
                    (user_id,),
                )
                self.conn.commit()
        except WereadError as e:
            result = {"ok": False, "synced": 0, "message": e.msg, "cookieInvalid": e.cookie_invalid}
            with self.lock:
                self.conn.execute(
                    "UPDATE weread_accounts SET last_sync_error=? WHERE user_id=?",
                    (e.msg, user_id),
                )
                self.conn.commit()
        except Exception as e:
            result = {"ok": False, "synced": 0, "message": f"同步出错：{e}", "cookieInvalid": False}
            with self.lock:
                self.conn.execute(
                    "UPDATE weread_accounts SET last_sync_error=? WHERE user_id=?",
                    (str(e), user_id),
                )
                self.conn.commit()
        finally:
            with self.lock:
                self.conn.execute(
                    "UPDATE weread_accounts SET syncing=0 WHERE user_id=?", (user_id,)
                )
                self.conn.commit()
        return result

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

    # ---------- 书单 ----------

    _BOOKLIST_STATUS = ("want", "reading", "finished")

    def add_booklist(self, user_id, title, author="", status="want", rating=0, note="") -> dict:
        title = (title or "").strip()
        if not title:
            raise ServiceError("书名不能为空")
        if len(title) > 80:
            raise ServiceError("书名最多 80 字")
        if status not in self._BOOKLIST_STATUS:
            status = "want"
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = 0
        rating = max(0, min(5, rating))
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO booklists(user_id, title, author, status, rating, note)
                   VALUES(?,?,?,?,?,?)""",
                (user_id, title, (author or "").strip(), status, rating, (note or "").strip()),
            )
            self.conn.commit()
            created_at = self.conn.execute(
                "SELECT created_at FROM booklists WHERE id=?", (cur.lastrowid,)
            ).fetchone()["created_at"]
        return self._booklist_map(
            {
                "id": cur.lastrowid,
                "title": title,
                "author": author or "",
                "status": status,
                "rating": rating,
                "note": note or "",
                "created_at": created_at or "",
            }
        )

    def list_booklists(self, user_id) -> list:
        with self.lock:
            rows = self.conn.execute(
                """SELECT id, title, author, status, rating, note, created_at
                   FROM booklists WHERE user_id=? ORDER BY id DESC""",
                (user_id,),
            ).fetchall()
        return [self._booklist_map(dict(r)) for r in rows]

    def update_booklist(self, user_id, bid, fields) -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT id FROM booklists WHERE id=? AND user_id=?", (bid, user_id)
            ).fetchone()
            if row is None:
                raise ServiceError("书单条目不存在", 404)
            sets, args = [], []
            if "title" in fields:
                t = (fields["title"] or "").strip()
                if not t:
                    raise ServiceError("书名不能为空")
                sets.append("title=?"); args.append(t)
            if "author" in fields:
                sets.append("author=?"); args.append((fields["author"] or "").strip())
            if "status" in fields:
                if fields["status"] not in self._BOOKLIST_STATUS:
                    raise ServiceError("非法的阅读状态")
                sets.append("status=?"); args.append(fields["status"])
            if "rating" in fields:
                try:
                    r = int(fields["rating"])
                except (TypeError, ValueError):
                    r = 0
                sets.append("rating=?"); args.append(max(0, min(5, r)))
            if "note" in fields:
                sets.append("note=?"); args.append((fields["note"] or "").strip())
            if sets:
                self.conn.execute(
                    "UPDATE booklists SET %s WHERE id=? AND user_id=?"
                    % ",".join(sets),
                    args + [bid, user_id],
                )
                self.conn.commit()
        return {"ok": True}

    def delete_booklist(self, user_id, bid) -> dict:
        with self.lock:
            cur = self.conn.execute(
                "DELETE FROM booklists WHERE id=? AND user_id=?", (bid, user_id)
            )
            self.conn.commit()
            if cur.rowcount == 0:
                raise ServiceError("书单条目不存在", 404)
        return {"ok": True}

    @staticmethod
    def _booklist_map(r) -> dict:
        return {
            "id": r["id"],
            "title": r["title"] or "",
            "author": r["author"] or "",
            "status": r["status"] or "want",
            "rating": r["rating"] or 0,
            "note": r["note"] or "",
            "createdAt": r["created_at"] or "",
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
                "SELECT id, openid, nickname, avatar FROM users"
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
                    "id": u["id"],
                    "name": name,
                    "avatar": u["avatar"] or "",
                    "streak": self._streak(u["id"]),
                    "total": totals.get(u["id"], 0),
                }
            )
        board.sort(key=lambda x: x["total"], reverse=True)
        return board[:limit] if limit > 0 else board

    # ---------- 心得帖 ----------

    def create_post(self, user_id: int, content: str, book_title: str = "", camp_id: int = 0) -> dict:
        content = (content or "").strip()
        if not content:
            raise ServiceError("心得内容不能为空")
        if len(content) > 500:
            raise ServiceError("心得内容最多 500 字")
        if camp_id:
            with self.lock:
                exists = self.conn.execute(
                    "SELECT 1 FROM camps WHERE id=?", (camp_id,)
                ).fetchone()
            if not exists:
                raise ServiceError("共读营不存在", 404)
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO posts(user_id, camp_id, content, book_title) VALUES(?,?,?,?)",
                (user_id, camp_id or None, content, (book_title or "").strip()),
            )
            self.conn.commit()
        return {"id": cur.lastrowid}

    def list_posts(self, user_id: int, camp_id: int = 0, limit: int = 50) -> list:
        sql = """SELECT p.id, p.content, p.book_title, p.camp_id, p.created_at,
                        u.nickname, u.openid, u.avatar,
                        (SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id=p.id) AS likes,
                        EXISTS(SELECT 1 FROM post_likes pl
                               WHERE pl.post_id=p.id AND pl.user_id=?) AS liked
                 FROM posts p JOIN users u ON u.id=p.user_id"""
        args = [user_id]
        if camp_id:
            sql += " WHERE p.camp_id=?"
            args.append(camp_id)
        sql += " ORDER BY p.id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["nickname"] or mask_openid(r["openid"] or ""),
                "avatar": r["avatar"] or "",
                "content": r["content"],
                "bookTitle": r["book_title"] or "",
                "campId": r["camp_id"] or 0,
                "likes": r["likes"],
                "likedByMe": bool(r["liked"]),
                "createdAt": r["created_at"] or "",
            }
            for r in rows
        ]

    def toggle_like(self, user_id: int, post_id: int) -> dict:
        with self.lock:
            if not self.conn.execute("SELECT 1 FROM posts WHERE id=?", (post_id,)).fetchone():
                raise ServiceError("帖子不存在", 404)
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO post_likes(post_id, user_id) VALUES(?,?)",
                (post_id, user_id),
            )
            liked = cur.rowcount > 0
            if not liked:
                self.conn.execute(
                    "DELETE FROM post_likes WHERE post_id=? AND user_id=?",
                    (post_id, user_id),
                )
            self.conn.commit()
            likes = self.conn.execute(
                "SELECT COUNT(*) FROM post_likes WHERE post_id=?", (post_id,)
            ).fetchone()[0]
        return {"liked": liked, "likes": likes}

    # ---------- 共读营 ----------

    def create_camp(self, user_id: int, name: str, book_title: str = "") -> dict:
        name = (name or "").strip()
        if not name:
            raise ServiceError("共读营名称不能为空")
        if len(name) > 30:
            raise ServiceError("共读营名称最多 30 字")
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO camps(name, book_title, creator_id) VALUES(?,?,?)",
                (name, (book_title or "").strip(), user_id),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO camp_members(camp_id, user_id) VALUES(?,?)",
                (cur.lastrowid, user_id),
            )
            self.conn.commit()
        return {"id": cur.lastrowid}

    def list_camps(self, user_id: int) -> list:
        with self.lock:
            rows = self.conn.execute(
                """SELECT c.id, c.name, c.book_title, c.created_at,
                          (SELECT COUNT(*) FROM camp_members m WHERE m.camp_id=c.id) AS members,
                          EXISTS(SELECT 1 FROM camp_members m
                                 WHERE m.camp_id=c.id AND m.user_id=?) AS joined
                   FROM camps c ORDER BY c.id DESC""",
                (user_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "bookTitle": r["book_title"] or "",
                "members": r["members"],
                "joined": bool(r["joined"]),
                "createdAt": r["created_at"] or "",
            }
            for r in rows
        ]

    def join_camp(self, user_id: int, camp_id: int) -> dict:
        with self.lock:
            if not self.conn.execute("SELECT 1 FROM camps WHERE id=?", (camp_id,)).fetchone():
                raise ServiceError("共读营不存在", 404)
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO camp_members(camp_id, user_id) VALUES(?,?)",
                (camp_id, user_id),
            )
            self.conn.commit()
        return {"joined": True, "firstTime": cur.rowcount > 0}

    def camp_detail(self, user_id: int, camp_id: int) -> dict:
        with self.lock:
            camp = self.conn.execute(
                "SELECT id, name, book_title, creator_id, created_at FROM camps WHERE id=?",
                (camp_id,),
            ).fetchone()
            if camp is None:
                raise ServiceError("共读营不存在", 404)
            members = self.conn.execute(
                """SELECT u.id, u.nickname, u.openid, u.avatar,
                          (SELECT COUNT(*) FROM checkins ck WHERE ck.user_id=u.id) AS total
                   FROM camp_members m JOIN users u ON u.id=m.user_id
                   WHERE m.camp_id=? ORDER BY m.id""",
                (camp_id,),
            ).fetchall()
        member_list = []
        for m in members:  # _streak 自带加锁，须在锁外调用
            member_list.append(
                {
                    "id": m["id"],
                    "name": m["nickname"] or mask_openid(m["openid"] or ""),
                    "avatar": m["avatar"] or "",
                    "streak": self._streak(m["id"]),
                    "total": m["total"],
                }
            )
        member_list.sort(key=lambda x: x["total"], reverse=True)
        return {
            "id": camp["id"],
            "name": camp["name"],
            "bookTitle": camp["book_title"] or "",
            "createdAt": camp["created_at"] or "",
            "joined": any(m["id"] == user_id for m in members),
            "members": member_list,
            "posts": self.list_posts(user_id, camp_id=camp_id),
        }

    def get_profile(self, user_id: int) -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT nickname, avatar FROM users WHERE id=?", (user_id,)
            ).fetchone()
        return {
            "nickname": row["nickname"] if row else "",
            "avatar": (row["avatar"] or "") if row else "",
        }

    def update_profile(self, user_id: int, nickname: str, avatar=None) -> None:
        with self.lock:
            if avatar is not None:
                self.conn.execute(
                    "UPDATE users SET nickname=?, avatar=? WHERE id=?",
                    (nickname, avatar, user_id),
                )
            else:
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
