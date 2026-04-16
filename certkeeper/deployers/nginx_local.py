"""本地 Nginx 部署（无需 SSH）。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from certkeeper.deployers.base import Deployer

logger = logging.getLogger(__name__)


class NginxLocalDeployer(Deployer):
    """将证书复制到本地 Nginx 目录并重载配置。"""

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        for field in ("cert_path", "reload_command"):
            if field not in self.config.settings:
                errors.append(f"{field} is required")
        return errors

    def deploy(self, domain: str, cert_path: Path, key_path: Path) -> dict[str, str]:
        cert_dir = str(self.config.settings["cert_path"])
        reload_command = str(self.config.settings["reload_command"])

        dest_cert = Path(cert_dir) / f"{domain}.pem"
        dest_key = Path(cert_dir) / f"{domain}.key"

        # 确保目标目录存在
        Path(cert_dir).mkdir(parents=True, exist_ok=True)

        # 复制证书和私钥
        logger.info("复制证书 %s -> %s", cert_path, dest_cert)
        shutil.copy2(str(cert_path), str(dest_cert))

        logger.info("复制私钥 %s -> %s", key_path, dest_key)
        shutil.copy2(str(key_path), str(dest_key))

        # 设置私钥权限为 600
        try:
            os.chmod(str(dest_key), 0o600)
        except OSError:
            logger.warning("无法设置私钥权限: %s", dest_key)

        # 执行重载命令
        logger.info("执行重载命令: %s", reload_command)
        result = subprocess.run(
            reload_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"重载命令失败 (exit {result.returncode}): {result.stderr.strip()}")

        return {
            "domain": domain,
            "target": self.config.name,
            "local_cert": str(dest_cert),
            "local_key": str(dest_key),
            "status": "success",
        }
