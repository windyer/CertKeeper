# CertKeeper

CertKeeper 是一个开源的 SSL/TLS 证书生命周期管理工具，基于 ACME 协议（Let's Encrypt）自动完成证书申请、续期、部署与邮件通知。

English version: [README.en.md](./README.en.md)

## 功能特性

- **自动证书申请与续期** — 基于 ACME 协议对接 Let's Encrypt，支持 `dns-01` 和 `http-01` 两种验证方式
- **多目标自动部署** — 续期后自动部署到 Nginx（SSH）、阿里云 CDN、腾讯云 CDN
- **邮件通知** — 证书即将到期提醒、续期/部署成功或失败实时通知
- **Web 管理界面** — 可视化管理证书、调度器、手动触发续期/部署
- **一键启动** — 单条命令同时启动 Web UI 和后台定时任务
- **可插拔架构** — DNS Provider、部署目标、通知渠道均为 Provider 模式，易于扩展

## 快速开始

### 环境要求

- Python 3.11+

### 安装

```bash
pip install -e .
```

### 1. 初始化配置

```bash
certkeeper init
```

生成 `certkeeper.yaml` 配置文件，按实际环境修改其中的参数。

### 2. 注册 ACME 账户

```bash
certkeeper register
```

### 3. 一键启动

```bash
# 前台启动（退出终端即停止）
certkeeper start

# 守护进程模式（后台运行，退出终端不会停止）
certkeeper start --daemon

# 查看守护进程状态
certkeeper start --status

# 停止守护进程
certkeeper start --stop
```

该命令同时启动 Web UI 和后台定时任务调度器。启动后访问 `http://127.0.0.1:8088` 进入管理界面。

使用 `--daemon` 模式时，进程在后台运行，PID 记录在 `data/certkeeper.pid` 文件中。关闭终端后服务不会被中断。

## CLI 命令

```bash
certkeeper init                    # 生成示例配置文件
certkeeper register                # 注册 ACME 账户密钥
certkeeper apply [--force]         # 续期+部署所有证书（--force 强制续期）
certkeeper renew <domain>          # 强制续期指定域名
certkeeper deploy <domain>         # 部署指定域名到配置目标
certkeeper list                    # 列出所有证书状态
certkeeper check                   # 干跑检查哪些证书即将到期
certkeeper web                     # 仅启动 Web UI
certkeeper daemon                  # 仅启动调度器守护进程
certkeeper start                   # 一键启动 Web UI + 调度器（前台）
certkeeper start --daemon          # 以守护进程模式启动（后台运行）
certkeeper start --status          # 查看守护进程状态
certkeeper start --stop            # 停止守护进程
certkeeper daemon --install        # 安装为系统服务
certkeeper daemon --uninstall      # 卸载系统服务
```

## 配置说明

配置文件为 `certkeeper.yaml`，完整示例参考 [certkeeper.yaml.example](./certkeeper.yaml.example)。

### ACME 配置

```yaml
acme:
  directory: https://acme-v02.api.letsencrypt.org/directory  # 生产环境
  # directory: https://acme-staging-v02.api.letsencrypt.org/directory  # 测试环境
  email: admin@example.com
  account_key: ./data/account.key
```

### 调度器

```yaml
scheduler:
  enabled: true          # 是否启用定时任务
  interval: daily        # 执行频率: daily / weekly
  time: "03:00"          # 每天执行时间（24小时制）
  reminder_days:       # 证书剩余天数 ≤ 此值时发送到期提醒邮件
```

定时任务执行流程：发送到期提醒 → 检查证书 → 自动续期 → 自动部署 → 发送结果通知。

### 邮件通知

```yaml
notifications:
  email-notify:
    type: smtp
    host: smtp.example.com       # SMTP 服务器
    port: 465                    # 端口（SSL: 465, TLS: 587）
    sender: certkeeper@example.com
    recipients: admin@example.com  # 多个用逗号分隔
    # username: ""               # SMTP 认证用户名（可选）
    # password: ""               # SMTP 认证密码（可选）
    use_ssl: true
```

配置后，以下场景会自动发送邮件：

| 场景 | 邮件标题 |
|------|---------|
| 证书即将到期 | [CertKeeper] 证书即将到期提醒 |
| 续期+部署成功 | [CertKeeper] 证书处理成功 |
| 续期+部署失败 | [CertKeeper] 证书处理失败 |

### DNS 提供商

```yaml
dns_providers:
  aliyun:
    type: aliyun
    access_key_id: ${ALIYUN_AK}
    access_key_secret: ${ALIYUN_SK}
```

敏感信息支持 `${ENV_VAR}` 语法从环境变量读取。

### 部署目标

```yaml
deployers:
  my-nginx:
    type: nginx-ssh
    host: 192.168.1.10
    user: root
    password: ""                   # 或使用 ssh_key_path
    cert_path: /etc/nginx/ssl
    reload_command: systemctl reload nginx

  aliyun-cdn:
    type: aliyun-cdn
    access_key_id: ${ALIYUN_AK}
    access_key_secret: ${ALIYUN_SK}

  tencent-cdn:
    type: tencent-cdn
    secret_id: ${TENCENT_SID}
    secret_key: ${TENCENT_SK}
```

### 证书列表

```yaml
certificates:
  - domain: example.com
    san:
      - www.example.com
    challenge: dns-01
    dns_provider: aliyun
    deploy_to:
      - my-nginx
      - aliyun-cdn
```

### Web 管理界面

```yaml
web_ui:
  enabled: true
  host: 127.0.0.1
  port: 8088
  session_secret: ${WEB_SESSION_SECRET}
  admin_username: admin
  admin_password_hash: ""  # 通过下方命令生成
```

生成管理员密码哈希：

```bash
python -c "from certkeeper.web.auth import hash_password; print(hash_password('你的密码'))"
```

## Web 管理界面

启动后访问 `http://127.0.0.1:8088`，支持以下功能：

- **证书概览** — 查看所有证书状态、剩余天数，一键续期/部署/删除
- **证书管理** — 新增、编辑、删除证书配置
- **调度器管理** — 启用/禁用定时任务、修改执行频率和提醒天数、暂停/恢复调度器、手动触发执行
- **操作通知** — 每次操作结果以页面提示反馈

## 项目结构

```
certkeeper/
├── cli.py                 # CLI 命令入口
├── config.py              # 配置加载与校验
├── runtime.py             # 运行时构建
├── acme_client/           # ACME 协议客户端
├── challenges/            # 验证方式 (dns-01, http-01)
├── core/
│   ├── manager.py         # 证书编排（检查、续期、部署、通知）
│   ├── scheduler.py       # 调度器
│   ├── daemon.py          # 守护进程管理
│   └── store.py           # 本地证书存储
├── deployers/             # 部署目标
│   ├── nginx_ssh.py       # Nginx (SSH)
│   ├── aliyun_cdn.py      # 阿里云 CDN
│   └── tencent_cdn.py     # 腾讯云 CDN
├── dns/                   # DNS 提供商
│   └── aliyun.py          # 阿里云 DNS
├── notifications/         # 通知渠道
│   └── email.py           # SMTP 邮件
└── web/                   # Web UI
    ├── app.py
    ├── auth.py
    ├── routes.py
    └── templates/
```

## 支持的 Provider

| 类型 | Provider | 说明 |
|------|----------|------|
| DNS | `aliyun` | 阿里云 DNS（DNS-01 验证） |
| 部署 | `nginx-ssh` | 通过 SSH 部署到 Nginx 服务器 |
| 部署 | `aliyun-cdn` | 部署到阿里云 CDN |
| 部署 | `tencent-cdn` | 部署到腾讯云 CDN |
| 通知 | `smtp` | SMTP 邮件通知 |

## 参与贡献

欢迎提交 Issue、建议与 Pull Request。
