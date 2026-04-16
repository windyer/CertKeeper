"""部署 Provider 抽象。"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Any

from certkeeper.providers import Provider, ProviderRegistry


class Deployer(Provider):
    """部署目标的基类。"""

    @abstractmethod
    def deploy(self, domain: str, cert_path: Path, key_path: Path) -> dict[str, Any]:
        """将证书材料部署到目标位置。"""


__all__ = ["Deployer", "ProviderRegistry"]
