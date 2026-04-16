"""阿里云 CDN 部署器。"""

from __future__ import annotations

from pathlib import Path

from certkeeper.deployers.base import Deployer


class AliyunCdnDeployer(Deployer):
    """最小化阿里云 CDN 部署器占位实现。"""

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        for field in ("access_key_id", "access_key_secret"):
            if field not in self.config.settings:
                errors.append(f"{field} is required")
        return errors

    def deploy(self, domain: str, cert_path: Path, key_path: Path) -> dict[str, str]:
        return {
            "domain": domain,
            "target": self.config.name,
            "cert_path": str(cert_path),
            "key_path": str(key_path),
            "status": "success",
        }
