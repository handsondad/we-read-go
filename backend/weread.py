"""微信读书网页端非官方接口客户端。

重要：这些接口不是官方公开 API，随时可能随网页改版失效。
本模块被设计为「可降级」：调用失败时由上层 service 决定如何处理（不影响核心打卡/提醒）。

稳定性设计：
- 瞬时网络错误（超时、连接中断、5xx）自动重试并退避，避免偶发抖动导致整次同步失败。
- 不跟随 302 跳转，从而能识别「Cookie 失效被重定向到登录页」的情况。
- 响应校验：非 JSON（登录页 HTML）、错误码 JSON 均视为 Cookie 失效，抛出可被上层捕获的 WereadError。
- 仅依赖标准库 urllib，无需第三方 HTTP 客户端。
"""
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://weread.qq.com/api"
_TIMEOUT = 10          # 单次请求超时（秒）
_RETRIES = 2           # 瞬时错误重试次数（共 1+2=3 次尝试）
_BACKOFF = 1.0         # 重试退避基数（秒），第 n 次等待 n*BACKOFF


class WereadError(Exception):
    """可被上层捕获的微信读书错误。cookie_invalid 表示需用户重新登录。"""

    def __init__(self, msg: str, cookie_invalid: bool = False):
        super().__init__(msg)
        self.msg = msg
        self.cookie_invalid = cookie_invalid


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 返回 None 表示不跟随重定向，便于识别登录跳转
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def _is_retryable(e: Exception) -> bool:
    if isinstance(e, socket.timeout):
        return True
    if isinstance(e, urllib.error.HTTPError):
        return 500 <= e.code < 600          # 仅服务端错误重试，4xx（含 401/403）不重试
    if isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return True
    return False


class Client:
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
        """获取单本书的阅读进度（0-100）。失败返回 0，不影响整体同步。"""
        try:
            return int(json.loads(self._get("/book/readinfo", {"bookId": book_id})).get("readingProgress", 0))
        except Exception:
            return 0

    def read_data(self) -> bytes:
        """拉取阅读统计（时长、天数等），原样返回供上层存储。"""
        return self._get("/readdata")
