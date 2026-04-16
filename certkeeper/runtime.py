"""CLI 与 Web UI 共享的运行时构建逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from certkeeper.acme_client.client import AcmeClient
from certkeeper.challenges.dns01 import Dns01ChallengeHandler
from certkeeper.challenges.http01 import Http01ChallengeHandler
from certkeeper.config import AppConfig, load_config
from certkeeper.core.manager import Manager
from certkeeper.core.store import Store
from certkeeper.deployers.aliyun_cdn import AliyunCdnDeployer
from certkeeper.deployers.base import Deployer, ProviderRegistry as DeployerRegistry
from certkeeper.deployers.nginx_local import NginxLocalDeployer
from certkeeper.deployers.nginx_ssh import NginxSshDeployer
from certkeeper.deployers.tencent_cdn import TencentCdnDeployer
from certkeeper.dns.aliyun import AliyunDnsProvider
from certkeeper.dns.base import DnsProvider, ProviderRegistry as DnsProviderRegistry
from certkeeper.notifications.base import Notifier, ProviderRegistry as NotifierRegistry
from certkeeper.notifications.email import EmailNotifier


@dataclass(slots=True)
class AppRuntime:
    config: AppConfig
    store: Store
    manager: Manager


def build_runtime(config_path: str | Path) -> AppRuntime:
    """根据配置文件构建共享运行时。"""

    resolved_config_path = Path(config_path)
    config = load_config(resolved_config_path)
    store = Store(resolved_config_path.parent / "data")

    deployer_registry = DeployerRegistry(Deployer)
    deployer_registry.register("nginx-ssh", NginxSshDeployer)
    deployer_registry.register("nginx-local", NginxLocalDeployer)
    deployer_registry.register("tencent-cdn", TencentCdnDeployer)
    deployer_registry.register("aliyun-cdn", AliyunCdnDeployer)

    notifier_registry = NotifierRegistry(Notifier)
    notifier_registry.register("smtp", EmailNotifier)

    dns_registry = DnsProviderRegistry(DnsProvider)
    dns_registry.register("aliyun", AliyunDnsProvider)

    challenge_handlers = {
        "http-01": Http01ChallengeHandler(),
        "dns-01": Dns01ChallengeHandler(
            dns_provider_configs=config.dns_providers,
            provider_registry=dns_registry,
        ),
    }

    manager = Manager(
        config=config,
        store=store,
        acme_client=AcmeClient(config.acme),
        challenge_handlers=challenge_handlers,
        deployer_registry=deployer_registry,
        notifier_registry=notifier_registry,
    )

    return AppRuntime(config=config, store=store, manager=manager)
