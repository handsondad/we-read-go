"""AES 对称加密封装，用于存储微信读书 Cookie。

密钥由配置中的 ENCRYPT_KEY 经 SHA-256 派生。底层优先使用 cryptography 的
Fernet（等价于 AES-128-CBC + HMAC 认证，可防篡改）。若 cryptography 未安装，
会在构造时抛出清晰的安装提示，而不是悄悄降级为明文。
"""
import base64
import hashlib


class Cipher:
    def __init__(self, key: str):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise RuntimeError(
                "缺少 cryptography 库，无法加密存储微信读书 Cookie。\n"
                "请运行: pip install cryptography\n"
                "或将其加入 requirements.txt 后重新安装依赖。"
            )
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
        self._f = Fernet(derived)

    def encrypt(self, plain: str) -> str:
        return self._f.encrypt(plain.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode("utf-8")).decode("utf-8")
