"""部署目标和 DNS 提供商的字段元数据定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FieldDef:
    """表单字段定义。"""

    name: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""


# ── 部署目标类型 ──

DEPLOYER_TYPES: dict[str, list[FieldDef]] = {
    "nginx-ssh": [
        FieldDef("host", "主机地址", placeholder="47.110.50.226"),
        FieldDef("port", "SSH 端口", required=False, placeholder="22"),
        FieldDef("user", "用户名", placeholder="deploy"),
        FieldDef("password", "密码", secret=True, required=False),
        FieldDef("ssh_key_path", "SSH 密钥路径", required=False, placeholder="~/.ssh/id_rsa"),
        FieldDef("cert_path", "证书目录", placeholder="/etc/nginx/conf"),
        FieldDef("reload_command", "重载命令", placeholder="systemctl restart nginx"),
        FieldDef("sudo", "使用 sudo", required=False),
    ],
    "nginx-local": [
        FieldDef("cert_path", "证书目录", placeholder="/etc/nginx/conf"),
        FieldDef("reload_command", "重载命令", placeholder="systemctl restart nginx"),
    ],
    "aliyun-cdn": [
        FieldDef("access_key_id", "Access Key ID"),
        FieldDef("access_key_secret", "Access Key Secret", secret=True),
    ],
    "tencent-cdn": [
        FieldDef("secret_id", "SecretId"),
        FieldDef("secret_key", "SecretKey", secret=True),
    ],
}

DEPLOYER_TYPE_LABELS: dict[str, str] = {
    "nginx-ssh": "Nginx (SSH)",
    "nginx-local": "Nginx (本地)",
    "aliyun-cdn": "阿里云 CDN",
    "tencent-cdn": "腾讯云 CDN",
}

# ── DNS 提供商类型 ──

DNS_PROVIDER_TYPES: dict[str, list[FieldDef]] = {
    "aliyun": [
        FieldDef("access_key_id", "Access Key ID"),
        FieldDef("access_key_secret", "Access Key Secret", secret=True),
    ],
}

DNS_PROVIDER_TYPE_LABELS: dict[str, str] = {
    "aliyun": "阿里云 DNS",
}

# ── 敏感字段名集合（用于掩码判断）──

SENSITIVE_FIELDS: set[str] = {
    f.name
    for fields in list(DEPLOYER_TYPES.values()) + list(DNS_PROVIDER_TYPES.values())
    for f in fields
    if f.secret
}
