"""ACME 账户密钥管理。"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class AcmeAccountService:
    """管理 ACME 账户 RSA 密钥材料。"""

    def ensure_account_key(self, account_key_path: str | Path) -> Path:
        """确保账户密钥文件存在，不存在则生成 2048 位 RSA 密钥。"""
        key_path = Path(account_key_path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            key_path.write_bytes(pem)
        return key_path

    def load_private_key(self, account_key_path: str | Path):
        """加载 PEM 格式的 RSA 私钥。"""
        key_path = Path(account_key_path)
        return load_pem_private_key(key_path.read_bytes(), password=None)
