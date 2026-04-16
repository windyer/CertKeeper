"""腾讯云 CDN 部署器。"""

from __future__ import annotations

import logging
from pathlib import Path

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.cdn.v20180606 import cdn_client, models

from certkeeper.deployers.base import Deployer

logger = logging.getLogger(__name__)


class TencentCdnDeployer(Deployer):
    """通过腾讯云 API 将证书部署到 CDN。"""

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        for field in ("secret_id", "secret_key"):
            if field not in self.config.settings:
                errors.append(f"{field} is required")
        return errors

    def _create_client(self) -> cdn_client.CdnClient:
        """创建腾讯云 CDN 客户端。"""
        cred = credential.Credential(
            str(self.config.settings["secret_id"]),
            str(self.config.settings["secret_key"]),
        )
        return cdn_client.CdnClient(cred, "")

    def deploy(self, domain: str, cert_path: Path, key_path: Path) -> dict[str, str]:
        client = self._create_client()

        cert_pem = cert_path.read_text(encoding="utf-8").strip()
        key_pem = key_path.read_text(encoding="utf-8").strip()

        # 构造证书信息
        cert_info = models.ServerCert()
        cert_info.Certificate = cert_pem
        cert_info.PrivateKey = key_pem
        cert_info.CertName = f"CertKeeper-{domain}"
        cert_info.Message = f"Auto-deployed by CertKeeper"

        # 构造 HTTPS 配置
        https = models.Https()
        https.Switch = "on"
        https.CertInfo = cert_info

        # 通过 UpdateDomainConfig 一次性上传证书并配置 HTTPS
        req = models.UpdateDomainConfigRequest()
        req.Domain = domain
        req.Https = https

        logger.info("正在为腾讯云 CDN 域名 %s 部署证书", domain)
        try:
            client.UpdateDomainConfig(req)
            logger.info("腾讯云 CDN 证书部署完成")
        except TencentCloudSDKException as e:
            raise RuntimeError(f"腾讯云 CDN 证书部署失败: {e}") from e

        return {
            "domain": domain,
            "target": self.config.name,
            "status": "success",
        }
