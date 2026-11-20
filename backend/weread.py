"""微信读书客户端：优先使用官方 Skills API，保留旧版网页 Cookie 客户端作兼容。"""
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://weread.qq.com/api"
GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
SKILL_VERSION = "1.0.3"
_TIMEOUT = 10          # 单次请求超时（秒）
_RETRIES = 2           # 瞬时错误重试次数（共 1+2=3 次尝试）
_BACKOFF = 1.0         # 重试退避基数（秒），第 n 次等待 n*BACKOFF


class WereadError(Exception):
    """可被上层捕获的微信读书错误。"""

    def __init__(self, msg: str, cookie_invalid: bool = False, api_key_invalid: bool = False,
                 upgrade_required: bool = False):
        super().__init__(msg)
        self.msg = msg
        self.cookie_invalid = cookie_invalid
        self.api_key_invalid = api_key_invalid
        self.upgrade_required = upgrade_required


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 返回 None 表示不跟随重定向，便于识别登录跳转
        return None


_opener = urllib.request.build_opener(_NoRedirect())


class ApiKeyClient:
    """微信读书官方 Skills API 客户端。"""

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def _call(self, api_name: str, **params) -> dict:
        body = {"api_name": api_name, **params, "skill_version": SKILL_VERSION}
        req = urllib.request.Request(
            GATEWAY,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise WereadError("微信读书 API Key 无效或已过期", api_key_invalid=True)
            raise WereadError(f"微信读书官方接口异常 (HTTP {e.code})")
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            raise WereadError(f"无法连接微信读书官方接口：{e}")
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise WereadError(f"微信读书官方接口返回无效数据：{e}")

        if not isinstance(payload, dict):
            raise WereadError("微信读书官方接口返回格式异常")
        upgrade = payload.get("upgrade_info")
        if upgrade:
            message = upgrade.get("message") if isinstance(upgrade, dict) else None
            raise WereadError(message or "请更新微信读书 Skills 后重试", upgrade_required=True)
        if payload.get("errcode"):
            raise WereadError(payload.get("errmsg") or "微信读书官方接口调用失败")
        return payload

    def shelf(self) -> list:
        payload = self._call("/shelf/sync")
        if not isinstance(payload.get("books"), list):
            raise WereadError("微信读书书架数据缺少 books 数组，未更新已有书架")
        books = []
        for book in payload.get("books", []):
            item = dict(book)
            item["status"] = "finished" if item.get("finishReading") == 1 else "reading"
            books.append(item)
        return books

    def read_progress(self, book_id: str) -> dict:
        payload = self._call("/book/getprogress", bookId=book_id)
        book = payload.get("book")
        if not isinstance(book, dict) or not isinstance(book.get("progress"), int):
            raise WereadError("微信读书未返回有效阅读进度")
        if not 0 <= book["progress"] <= 100:
            raise WereadError("微信读书阅读进度超出有效范围")
        return book

    def read_data(self) -> dict:
        return self._call("/readdata/detail", mode="overall")


def _is_retryable(e: Exception) -> bool:
    if isinstance(e, socket.timeout):
        return True
    if isinstance(e, urllib.error.HTTPError):
        return 500 <= e.code < 600          # 仅服务端错误重试，4xx（含 401/403）不重试
    if isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return True
    return False


class Client:
    """旧版网页端接口客户端，可能随网页改版失效。"""

    def __init__(self, cookie: str, ua: str):
        self.cookie = cookie
        self.ua = ua

    def _get(self, path: str, query: dict = None) -> bytes:
        url = BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Cookie": self.cookie,
            "User-Agent": self.ua,
            "Referer": "https://weread.qq.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "identity",
        }
        last = None
        for attempt in range(_RETRIES + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                resp = _opener.open(req, timeout=_TIMEOUT)
                if resp.status >= 300:
                    # 多为 Cookie 失效后的登录跳转
                    raise WereadError("微信读书 Cookie 已失效，请重新登录后复制", cookie_invalid=True)
                raw = resp.read()
                self._validate(raw)
                return raw
            except WereadError:
                raise
            except Exception as e:  # 瞬时错误重试
                last = e
                if not _is_retryable(e) or attempt >= _RETRIES:
                    break
                time.sleep(_BACKOFF * (attempt + 1))
        # 全部尝试失败，给出可操作信息
        if isinstance(last, urllib.error.HTTPError):
            if last.code in (401, 403):
                raise WereadError("微信读书 Cookie 无效或权限不足", cookie_invalid=True)
            raise WereadError(f"微信读书接口异常 (HTTP {last.code})")
        raise WereadError(f"无法连接微信读书服务：{last}")

    @staticmethod
    def _validate(raw: bytes) -> None:
        # 非 JSON（登录页 HTML 等）视为 Cookie 失效
        if not raw or raw[:1] not in (b"{", b"["):
            raise WereadError("微信读书返回非预期内容，Cookie 可能已失效", cookie_invalid=True)
        try:
            obj = json.loads(raw)
        except Exception:
            raise WereadError("微信读书返回非 JSON，Cookie 可能已失效", cookie_invalid=True)
        if isinstance(obj, dict):
            if obj.get("errcode") or (isinstance(obj.get("code"), int) and obj.get("code") < 0):
                raise WereadError(obj.get("errmsg") or "微信读书返回错误，Cookie 可能已失效",
                                   cookie_invalid=True)

    def shelf(self) -> list:
        """拉取书架：当前在读 + 已读完。任一列表失败（多因 Cookie 失效）直接抛出 WereadError。"""
        out = []
        for path, status in (("/shelf/current", "reading"), ("/shelf/finish", "finished")):
            payload = json.loads(self._get(path))
            merged = []
            merged += payload.get("recentBooks", [])
            merged += payload.get("books", [])
            merged += payload.get("finishReadBooks", [])
            for b in merged:
                b = dict(b)
                b["status"] = status
                out.append(b)
        return out

    def notebook(self) -> dict:
        """返回各本书的笔记数量，key 为 bookId。上层按需调用。"""
        payload = json.loads(self._get("/user/notebook"))
        return {b["bookId"]: b.get("noteCount", 0) for b in payload.get("books", [])}

    def read_info(self, book_id: str) -> int:
        """获取旧版单本书进度，失败交由业务层保留已有数据。"""
        payload = json.loads(self._get("/book/readinfo", {"bookId": book_id}))
        try:
            progress = int(payload["readingProgress"])
        except (KeyError, TypeError, ValueError):
            raise WereadError("微信读书未返回有效阅读进度")
        if not 0 <= progress <= 100:
            raise WereadError("微信读书阅读进度超出有效范围")
        return progress

    def read_data(self) -> bytes:
        """拉取阅读统计（时长、天数等），原样返回供上层存储。"""
        return self._get("/readdata")
