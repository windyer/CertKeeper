# ACME 证书申请真实实现设计

日期：2026-04-15

## 概述

将 CertKeeper 的 3 个占位实现改为真实功能：ACME 协议客户端、ACME 账户密钥管理、阿里云 DNS API 调用。实现后可以通过 Web UI 点击"执行 apply"完成真实的 Let's Encrypt 证书申请。

## 范围

- ACME 协议客户端（RFC 8555）
- ACME 账户密钥生成与注册
- 阿里云 DNS API（DNS-01 验证）
- 不含：部署器、HTTP-01、通知（后续迭代）

## 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| ACME 实现方式 | 自己实现（cryptography + requests） | 不引入新依赖，完全可控 |
| 代码组织 | 单一 AcmeClient 类 | ~250 行，拆分无必要 |
| 测试环境 | 先 staging 后生产 | 避免速率限制 |

## 文件改动

### 1. `certkeeper/acme_client/account.py`

将占位改为真实 RSA 密钥生成和加载：

- `ensure_account_key(path)` — 检查密钥文件是否存在
  - 存在：加载 PEM 格式 RSA 私钥
  - 不存在：生成 2048 位 RSA 私钥，写为 PEM 文件
- 返回密钥路径

### 2. `certkeeper/acme_client/client.py`

将占位改为完整 ACME RFC 8555 实现：

**JWS 签名**（内部方法）：
- ` _jws_sign(url, payload, nonce, kid, private_key)` — RS256 签名
- Protected Header: alg, nonce, url, kid（注册后）或 jwk（注册时）
- 用 cryptography.hazmat 进行 RSA PKCS1v15 签名

**ACME 流程方法**：
- `_get_directory()` — GET 目录，缓存 nonce
- `_get_nonce()` — HEAD newNonce 获取 anti-replay nonce
- `_register_account(private_key)` — POST newAccount，返回 kid
- `_create_order(kid, private_key, domains)` — POST newOrder
- `_get_authorization(kid, private_key, auth_url)` — GET authorization
- `_trigger_challenge(kid, private_key, challenge_url)` — POST challenge
- `_poll_challenge(kid, private_key, challenge_url)` — 轮询直到 valid/失败
- `_finalize_order(kid, private_key, finalize_url, csr)` — POST finalize
- `_download_certificate(kid, private_key, cert_url)` — GET 证书链

**主入口**（接口不变）：
- `obtain_certificate(certificate, challenge_handler) -> CertificateMaterial`
  - 加载/生成账户密钥
  - 执行完整 ACME 流程
  - 调用 challenge_handler.prepare() 触发 DNS 记录
  - 等待验证完成
  - 调用 challenge_handler.cleanup() 清理
  - 生成域名私钥 + CSR
  - 下载证书链
  - 返回 CertificateMaterial

**CSR 生成**（内部）：
- 用 cryptography 生成 2048 位 RSA 域名私钥
- 用域名私钥生成 CSR，包含 domain + SAN

**错误处理**：
- ACME 错误（urn:acme:error:*）解析为异常
- 网络超时重试（最多 3 次）
- 验证失败轮询超时（最多 120 秒）

### 3. `certkeeper/dns/aliyun.py`

将占位改为真实阿里云 DNS API 调用：

**API 端点**：`https://alidns.aliyuncs.com/`

**公共参数**：
- AccessKeyId, SignatureMethod(HMAC-SHA1), SignatureVersion(1.0), Timestamp, Version(2015-01-09), Format(JSON)

**签名**（内部方法）：
- `_sign(params, access_key_secret)` — 参数按 key 字典序排列，HMAC-SHA1 签名，Base64 编码

**`create_txt_record(domain, name, value)`**：
- 解析出 DomainName 和 RR（从 name 中提取 `_acme-challenge.subdomain`）
- 调用 `AddDomainRecord` API
- 轮询 DNS 查询确认 TXT 记录生效（最多 60 秒）

**`delete_txt_record(domain, name, value)`**：
- 调用 `DescribeDomainRecords` 查询 RecordId
- 调用 `DeleteDomainRecord` 删除

## 不改动的文件

- `core/manager.py` — 编排逻辑完整，接口匹配
- `core/store.py` — 证书存储和解析已真实
- `challenges/dns01.py` — 已真实实现，调用 provider 的 create/delete
- 所有 base.py 抽象基类
- Web UI 相关文件
