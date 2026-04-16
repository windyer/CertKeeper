# 证书配置管理 UI 设计

日期：2026-04-14

## 概述

在 CertKeeper Web UI 中添加证书配置的完整 CRUD 功能，用户可以在界面上新增、查看、编辑、删除证书配置，无需手动编辑 certkeeper.yaml 文件。

## 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 方案 | 在 Dashboard 列表扩展 | 改动小，复用现有结构，符合项目规模 |
| 布局 | 单页表单 | 字段不多，无需分步向导 |
| Domain 修改 | 创建后不可修改 | domain 是存储路径标识，避免迁移复杂度 |
| SAN 字段 | 可选，默认隐藏 | 单域名证书不需要 SAN |
| 持久化 | 直接写回 certkeeper.yaml | 单一配置源，简单可靠 |
| 确认机制 | 无需确认，flash 提示 | 操作简单，flash 已足够反馈 |

## 数据模型

复用现有 `CertificateConfig`，不做修改：

```python
@dataclass
class CertificateConfig:
    domain: str              # 主域名，创建后不可修改
    san: list[str]           # 备用域名列表，可选
    challenge: str           # "dns-01" 或 "http-01"
    dns_provider: str | None # DNS 提供商（dns-01 时必填）
    http_root: str | None    # HTTP 根路径（http-01 时必填）
    deploy_to: list[str]     # 部署目标列表，至少选一个
```

## 路由设计

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/certificates/new` | 显示新增证书表单 |
| POST | `/certificates` | 提交新增证书 |
| GET | `/certificates/{domain}/edit` | 显示编辑表单（domain 只读） |
| POST | `/certificates/{domain}` | 提交编辑 |
| POST | `/certificates/{domain}/delete` | 删除证书配置 |

所有路由需要登录认证（`@require_auth`），POST 路由需要 CSRF token。

## 表单设计

新增模板 `certificate_form.html`，复用 `base.html` 布局。

### 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| domain | 文本输入 | 是 | 编辑模式下只读（灰色背景） |
| san | 动态列表 | 否 | 默认隐藏，点击"添加备用域名"展开，每行一个域名，可增减 |
| challenge | 下拉选择 | 是 | dns-01 / http-01，切换时显示/隐藏对应字段 |
| dns_provider | 下拉选择 | 条件必填 | challenge=dns-01 时显示，从已注册 provider 列表获取 |
| http_root | 文本输入 | 条件必填 | challenge=http-01 时显示 |
| deploy_to | 复选框列表 | 是（至少一个） | 从已注册 deployer 列表获取 |

### 验证规则

- domain 必填，格式校验为合法域名
- domain 新增时不可与已有证书重复
- challenge 必选
- dns-01 时 dns_provider 必填；http-01 时 http_root 必填
- deploy_to 至少选一个
- 验证失败返回表单页，保留已填数据并显示错误信息

## Dashboard 改动

- 证书列表表格每行末尾增加"编辑"和"删除"按钮
- 列表上方或下方增加"新增证书"按钮
- 删除按钮用 POST 表单提交（防止 CSRF）

## 持久化

- `config.py` 新增 `save_config(config)` 方法
- 写回 certkeeper.yaml，只修改 `certificates` 列表部分
- 保持 acme、scheduler、web_ui 等其他配置不变
- domain 参数做路径校验，防止路径遍历攻击

## 安全

- 复用现有 `@require_auth` 登录认证
- 复用现有 CSRF token 机制
- domain 参数路径校验，防止路径遍历

## 涉及文件

### 新增

- `certkeeper/web/templates/certificate_form.html`

### 修改

- `certkeeper/web/routes.py` — 新增 5 个路由
- `certkeeper/config.py` — 新增 `save_config()` 方法
- `certkeeper/web/templates/dashboard.html` — 增加操作按钮

### 不动

- `base.html`、`auth.py`、`app.py`
- `CertificateConfig` 数据模型
