"""HTTP-01 challenge 处理器。"""

from __future__ import annotations

from pathlib import Path

from certkeeper.challenges.base import ChallengeHandler
from certkeeper.config import CertificateConfig


class Http01ChallengeHandler(ChallengeHandler):
    """为 HTTP-01 校验准备 webroot 目录和验证文件。"""

    def prepare(self, certificate: CertificateConfig, validation: str = "") -> None:
        if not certificate.http_root:
            raise ValueError("http_root is required for http-01 challenges.")

        challenge_dir = Path(certificate.http_root) / ".well-known" / "acme-challenge"
        challenge_dir.mkdir(parents=True, exist_ok=True)

        if validation and certificate.domain:
            token = validation.split(".")[0] if "." in validation else "token"
            (challenge_dir / token).write_text(validation, encoding="utf-8")

    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        # 保留目录，便于后续续期直接复用。
        _ = certificate
