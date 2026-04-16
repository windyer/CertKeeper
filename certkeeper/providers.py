"""共享的 Provider 抽象与注册表支持。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from certkeeper.config import NamedResourceConfig
from certkeeper.exceptions import ConfigurationError


class Provider(ABC):
    """具名 Provider 的公共基类。"""

    def __init__(self, config: NamedResourceConfig) -> None:
        self.config = config

    @abstractmethod
    def validate_config(self) -> list[str]:
        """返回 Provider 配置的校验错误。"""


ProviderType = TypeVar("ProviderType", bound=Provider)


class ProviderRegistry(Generic[ProviderType]):
    """根据配置中的 type 名称创建 Provider 实例。"""

    def __init__(self, provider_base: type[ProviderType]) -> None:
        self.provider_base = provider_base
        self._registry: dict[str, type[ProviderType]] = {}

    def register(self, type_name: str, provider_cls: type[ProviderType]) -> None:
        if not issubclass(provider_cls, self.provider_base):
            raise TypeError(f"{provider_cls.__name__} must inherit {self.provider_base.__name__}")
        self._registry[type_name] = provider_cls

    def create(self, config: NamedResourceConfig) -> ProviderType:
        provider_cls = self._registry.get(config.type)
        if provider_cls is None:
            raise ConfigurationError(f"Unknown provider type '{config.type}' for resource '{config.name}'.")

        provider = provider_cls(config)
        errors = provider.validate_config()
        if errors:
            raise ConfigurationError(
                f"Invalid configuration for resource '{config.name}': {'; '.join(errors)}"
            )
        return provider
