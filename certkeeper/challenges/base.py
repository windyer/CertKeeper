"""Challenge 处理器抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from certkeeper.config import CertificateConfig


class ChallengeHandler(ABC):
    """ACME challenge 处理器基类。"""

    @abstractmethod
    def prepare(self, certificate: CertificateConfig, validation: str = "") -> None:
        """准备 challenge 校验所需资源。"""

    @abstractmethod
    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        """清理 challenge 校验相关资源。"""
