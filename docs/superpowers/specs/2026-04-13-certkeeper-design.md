# CertKeeper 设计规格

## 概述

CertKeeper 是一个 Python CLI 工具，用于自动化管理 SSL/TLS 证书。通过 Let's Encrypt 的 ACME 协议申请和续期证书，然后部署到 nginx 服务器和云 CDN 服务。工具以守护进程模式运行，内置调度器，彻底告别手动续期。

**痛点**：免费 TLS 证书每 90 天过期，手动续期容易遗忘，导致证书过期、网站不可用。

**方案**：可配置的守护进程，自动监控证书到期时间，通过 ACME 自动续期，部署到配置的目标——成功或失败均发送通知。

## 技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | ACME / 云 SDK 生态成熟 |
| ACME 客户端 | `acme` 库（certbot 项目） | 经过实战验证的协议处理 |
| CLI 框架 | `click` | 组合式命令，装饰器风格 |
| 调度器 | `APScheduler` | 轻量、跨平台 |
| 配置格式 | YAML | 可读性好，支持环境变量替换 |
| 云 SDK | `alibabacloud-cdn`、`tencentcloud-sdk-python` | 官方 SDK |

## 架构

三层架构：CLI → 核心引擎 → Provider。

```
┌─────────────────────────────────────────┐
│           CLI (click)                    │
│  apply / daemon / list / check / ...    │
├─────────────────────────────────────────┤
│              核心引擎                    │
│  ┌──────────┐  ┌─────────────────────┐  │
│  │ 配置     │  │ 证书管理器          │  │
│  │ 加载器   │  │ (编排器)            │  │
│  └──────────┘  └─────────────────────┘  │
│  ┌──────────┐  ┌─────────────────────┐  │
│  │ 调度器   │  │ 存储                │  │
│  │ (APS)    │  │ (状态 + 证书文件)   │  │
│  └──────────┘  └─────────────────────┘  │
├─────────────────────────────────────────┤
│              Provider 层                │
│  ┌──────────┐  ┌───────────────────┐    │
│  │ACME      │  │ DNS Provider      │    │
│  │Client    │  │ (aliyun, ...)     │    │
│  └──────────┘  └───────────────────┘    │
│  ┌────────────────────────────────────┐  │
│  │ 部署器 (Deployer)                  │  │
│  │ (nginx-ssh, tencent-cdn,          │  │
│  │  aliyun-cdn, ...)                 │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 通知器 (Notifier)                  │  │
│  │ (smtp-email, webhook, ...)        │  │
│  └────────────────────────────────────┘  │
├─────────────────────────────────────────┤
│           存储                           │
│  data/account.key                        │
│  data/certs/<domain>/*.pem              │
│  data/state.json                        │
└─────────────────────────────────────────┘
```

## 配置文件（YAML）

```yaml
# certkeeper.yaml

acme:
  directory: https://acme-v02.api.letsencrypt.org/directory
  email: admin@example.com
  account_key: ./data/account.key

scheduler:
  enabled: true
  interval: daily
  time: "03:00"

notifications:
  email:
    type: smtp
    host: smtp.example.com
    port: 465
    sender: certkeeper@example.com
    password: ${SMTP_PASSWORD}
    recipients: [admin@example.com]

dns_providers:
  aliyun:
    type: aliyun
    access_key_id: ${ALIYUN_AK}
    access_key_secret: ${ALIYUN_SK}

deployers:
  nginx-web:
    type: nginx-ssh
    host: 1.2.3.4
    user: root
    cert_path: /etc/nginx/ssl/
    reload_command: systemctl reload nginx

  nginx-api:
    type: nginx-ssh
    host: 5.6.7.8
    user: deploy
    cert_path: /etc/nginx/ssl/
    reload_command: systemctl reload nginx

  tencent-cdn-site:
    type: tencent-cdn
    secret_id: ${TENCENT_SID}
    secret_key: ${TENCENT_SK}

  tencent-cdn-static:
    type: tencent-cdn
    secret_id: ${TENCENT_SID}
    secret_key: ${TENCENT_SK}

  aliyun-cdn:
    type: aliyun-cdn
    access_key_id: ${ALIYUN_AK}
    access_key_secret: ${ALIYUN_SK}

certificates:
  - domain: example.com
    san: [www.example.com, api.example.com]
    challenge: dns-01
    dns_provider: aliyun
    deploy_to: [nginx-web, tencent-cdn-site]

  - domain: cdn.example.com
    challenge: dns-01
    dns_provider: aliyun
    deploy_to: [tencent-cdn-static, aliyun-cdn]

  - domain: test.example.com
    challenge: http-01
    http_root: /var/www/html      # 本地路径（本机部署时）或
                                   # SSH 目标路径（通过 nginx-ssh 部署时）
    deploy_to: [nginx-web]
```

### 配置原则

- 敏感信息使用 `${ENV_VAR}` 语法，运行时从环境变量解析，不硬编码到配置文件
- `dns_providers`、`deployers`、`notifications` 为命名资源，`certificates` 通过名称引用
- 每个 `certificate` 条目是独立的续期单元
- 支持 SAN（多域名合并为一张证书）

## CLI 命令

```
certkeeper init                # 生成示例配置文件
certkeeper register            # 注册 ACME 账户（首次使用）
certkeeper apply               # 检查所有证书，续期即将到期的并部署
certkeeper apply --force       # 强制续期所有证书
certkeeper renew <domain>      # 续期单个域名
certkeeper deploy <domain>     # 仅部署（使用已有证书）
certkeeper list                # 列出所有证书状态
certkeeper check               # 干跑模式：显示哪些证书即将到期
certkeeper daemon              # 守护进程模式（前台运行）
certkeeper daemon --install    # 安装为系统服务
certkeeper daemon --uninstall  # 卸载系统服务
```

退出码：0 = 全部成功，1 = 部分失败，2 = 全部失败。

## 执行流程（apply）

```
apply 启动
  │
  ├─ 加载 certkeeper.yaml
  │
  ├─ 遍历每个 certificate 条目
  │   │
  │   ├─ 检查本地证书是否即将到期（< 30天）
  │   │   ├─ 未到期 → 跳过
  │   │   └─ 即将到期 / 无证书 → 继续
  │   │
  │   ├─ ACME 申请证书
  │   │   ├─ HTTP-01 → 写验证文件到目标路径
  │   │   └─ DNS-01 → 调用 DNS Provider API 添加 TXT 记录
  │   │
  │   ├─ 等待验证通过，下载证书
  │   │
  │   ├─ 保存证书到 data/certs/<domain>/
  │   │
  │   ├─ 遍历 deploy_to 列表，逐个部署
  │   │   ├─ nginx-ssh → SFTP 上传证书 + 执行 reload 命令
  │   │   ├─ tencent-cdn → 腾讯云 API 上传证书
  │   │   └─ aliyun-cdn → 阿里云 API 上传证书
  │   │
  │   └─ 记录结果
  │
  ├─ 汇总结果，发送通知
  │   ├─ 全部成功 → 成功通知
  │   └─ 有失败 → 失败通知（含失败详情）
  │
  └─ 退出（返回对应退出码）
```

## 守护进程模式

- `certkeeper daemon` 前台运行，使用 APScheduler 调度
- `--install` 在 Linux 生成 systemd unit 文件，在 Windows 注册为服务
- 读取 `scheduler` 配置段控制执行时间
- 内置日志输出到 stdout + 文件
- 后续：同一进程启动 Web UI

## Provider 插件模式

所有 Provider 遵循统一的抽象接口模式：

```python
# 示例：Deployer
class Deployer(ABC):
    @abstractmethod
    def deploy(self, domain: str, cert_path: Path, key_path: Path) -> DeployResult: ...

    @abstractmethod
    def validate_config(self) -> list[str]: ...
```

通过配置中的 `type` 字段映射到具体实现类，注册到全局 registry。新增 Provider 只需：
1. 实现抽象类
2. 注册 type 名称
3. 在配置中使用

## 项目结构

```
certkeeper/
├── pyproject.toml
├── certkeeper/
│   ├── __init__.py
│   ├── cli.py                  # CLI 入口 (click)
│   ├── config.py               # YAML 配置加载 + 校验
│   ├── core/
│   │   ├── __init__.py
│   │   ├── manager.py          # 证书续期编排器
│   │   ├── scheduler.py        # APScheduler 封装
│   │   └── store.py            # 证书存储（本地文件 + state.json）
│   ├── acme_client/
│   │   ├── __init__.py
│   │   ├── client.py           # acme 库封装
│   │   └── account.py          # 账户注册/管理
│   ├── challenges/
│   │   ├── __init__.py
│   │   ├── base.py             # ChallengeHandler 抽象基类
│   │   ├── http01.py           # HTTP-01 验证
│   │   └── dns01.py            # DNS-01 验证
│   ├── dns/
│   │   ├── __init__.py
│   │   ├── base.py             # DnsProvider 抽象基类
│   │   └── aliyun.py           # 阿里云 DNS API
│   ├── deployers/
│   │   ├── __init__.py
│   │   ├── base.py             # Deployer 抽象基类
│   │   ├── nginx_ssh.py        # nginx via SSH/SFTP
│   │   ├── tencent_cdn.py      # 腾讯云 CDN
│   │   └── aliyun_cdn.py       # 阿里云 CDN
│   └── notifications/
│       ├── __init__.py
│       ├── base.py             # Notifier 抽象基类
│       └── email.py            # SMTP 邮件通知
├── data/                       # 运行时数据（gitignore）
│   ├── account.key
│   ├── state.json
│   └── certs/<domain>/
│       ├── fullchain.pem
│       └── privkey.pem
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_manager.py
    └── test_deployers/
```

## 存储

- **证书文件**：`data/certs/<domain>/fullchain.pem` + `privkey.pem`
- **状态记录**：`data/state.json` — 每个域名的上次续期时间、到期时间、上次部署结果
- **账户密钥**：`data/account.key` — ACME 账户私钥，首次 `register` 时自动生成

## 通知触发时机

- 证书续期成功
- 证书续期失败
- 部署到某个目标成功/失败
- 证书即将到期（每次运行时检查，默认阈值：30天）

## 阶段规划

本规格覆盖 CLI + 守护进程阶段。后续阶段（不在初始实现范围内）：

- Web UI 配置管理与监控
- 更多 DNS Provider（Cloudflare、Route53 等）
- 更多部署目标（阿里云 OSS、阿里云 SLB 等）
- 更多通知渠道（webhook、Server酱、Telegram 等）
