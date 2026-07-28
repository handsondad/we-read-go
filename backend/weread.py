"""微信读书网页端非官方接口客户端。

重要：这些接口不是官方公开 API，随时可能随网页改版失效。
本模块被设计为「可降级」：调用失败时由上层 service 决定如何处理（不影响核心打卡/提醒）。
依赖标准库 urllib，无需第三方 HTTP 客户端。
"""
import json
import urllib.parse
import urllib.request

BASE = "https://weread.qq.com/api"


class Client:
    def __init__(self, cookie: str, ua: str):
        self.cookie = cookie
        self.ua = ua

    def _get(self, path: str, query: dict = None) -> bytes:
        url = BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(
            url,
            headers={
                "Cookie": self.cookie,
                "User-Agent": self.ua,
                "Referer": "https://weread.qq.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()

    def shelf(self) -> list:
        """拉取书架：当前在读 + 已读完。"""
        out = []
        for path, status in (("/shelf/current", "reading"), ("/shelf/finish", "finished")):
            try:
                raw = self._get(path)
            except Exception as e:
                raise RuntimeError(f"拉取书架失败({path}): {e}")
            payload = json.loads(raw)
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
        """返回各本书的笔记数量，key 为 bookId。"""
        raw = self._get("/user/notebook")
        payload = json.loads(raw)
        return {b["bookId"]: b.get("noteCount", 0) for b in payload.get("books", [])}

    def read_info(self, book_id: str) -> int:
        """获取单本书的阅读进度（0-100）。"""
        raw = self._get("/book/readinfo", {"bookId": book_id})
        return int(json.loads(raw).get("readingProgress", 0))

    def read_data(self) -> bytes:
        """拉取阅读统计（时长、天数等），原样返回供上层存储。"""
        return self._get("/readdata")
