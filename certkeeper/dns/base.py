"""DNS Provider 抽象。"""

from __future__ import annotations

from abc import abstractmethod

from certkeeper.providers import Provider, ProviderRegistry


class DnsProvider(Provider):
    """供 dns-01 challenge 使用的 DNS Provider 基类。"""

    @abstractmethod
    def create_txt_record(self, domain: str, name: str, value: str) -> None:
        """创建 TXT 记录。"""

    @abstractmethod
    def delete_txt_record(self, domain: str, name: str, value: str) -> None:
        """删除 TXT 记录。"""


__all__ = ["DnsProvider", "ProviderRegistry"]
