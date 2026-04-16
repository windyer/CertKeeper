"""CertKeeper 共享异常定义。"""


class CertKeeperError(Exception):
    """应用层错误的基类。"""


class ConfigurationError(CertKeeperError):
    """配置无效或不完整时抛出。"""


class FeatureNotImplementedError(CertKeeperError):
    """命令已暴露但尚未完整接通时抛出。"""
