from __future__ import annotations

import pytest

from certkeeper.config import NamedResourceConfig
from certkeeper.deployers.base import Deployer, ProviderRegistry
from certkeeper.exceptions import ConfigurationError


class ExampleDeployer(Deployer):
    def validate_config(self) -> list[str]:
        if "host" not in self.config.settings:
            return ["host is required"]
        return []

    def deploy(self, domain: str, cert_path, key_path):
        return {"domain": domain, "status": "success"}


def test_provider_registry_creates_registered_provider() -> None:
    registry = ProviderRegistry(Deployer)
    registry.register("example", ExampleDeployer)

    provider = registry.create(
        NamedResourceConfig(name="demo", type="example", settings={"host": "127.0.0.1"})
    )

    assert isinstance(provider, ExampleDeployer)


def test_provider_registry_rejects_invalid_provider_config() -> None:
    registry = ProviderRegistry(Deployer)
    registry.register("example", ExampleDeployer)

    with pytest.raises(ConfigurationError) as exc_info:
        registry.create(NamedResourceConfig(name="demo", type="example", settings={}))

    assert "host is required" in str(exc_info.value)
