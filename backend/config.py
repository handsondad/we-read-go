"""环境变量配置，等价于原 Go 版 config.go。所有项均有开箱可用的默认值。"""
import os
from dataclasses import dataclass


@dataclass
class Config:
    addr: str            # 监听地址 host:port
    db_path: str         # SQLite 文件路径
    encrypt_key: str     # Cookie 加密密钥（空则由 crypto 模块自动生成并持久化）
    wx_appid: str        # 微信小程序 AppID
    wx_appsecret: str    # 微信小程序 AppSecret
    wx_template_id: str  # 订阅消息模板 ID
    weread_ua: str       # 请求微信读书接口所用 User-Agent


def load() -> Config:
    return Config(
        addr=os.environ.get("ADDR", "0.0.0.0:8080"),
        db_path=os.environ.get("DB_PATH", "we_read.db"),
        encrypt_key=os.environ.get("ENCRYPT_KEY", ""),
        wx_appid=os.environ.get("WX_APPID", ""),
        wx_appsecret=os.environ.get("WX_APPSECRET", ""),
        wx_template_id=os.environ.get("WX_TEMPLATE_ID", ""),
        weread_ua=os.environ.get(
            "WEREAD_UA",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        ),
    )
