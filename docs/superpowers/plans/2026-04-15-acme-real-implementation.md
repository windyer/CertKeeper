# ACME 证书申请真实实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 ACME 协议客户端 + 阿里云 DNS API，让 CertKeeper 可以真正从 Let's Encrypt 申请 SSL 证书。

**Architecture:** 在现有 AcmeClient 接口不变的前提下，将 3 个占位文件替换为真实实现。同时需要给 ChallengeHandler 接口添加 validation 参数，使 ACME 客户端可以将计算出的验证值传给 handler。

**Tech Stack:** Python 3.11+, cryptography (RSA/JWS), requests (HTTP), hmac/hashlib (阿里云签名)

---

### Task 1: account.py — RSA 密钥生成与加载

**Files:**
- Modify: `certkeeper/acme_client/account.py`

- [ ] **Step 1: 替换 `certkeeper/acme_client/account.py` 全部内容**

```python
"""ACME 账户密钥管理。"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class AcmeAccountService:
    """管理 ACME 账户 RSA 密钥材料。"""

    def ensure_account_key(self, account_key_path: str | Path) -> Path:
        """确保账户密钥文件存在，不存在则生成 2048 位 RSA 密钥。"""
        key_path = Path(account_key_path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            key_path.write_bytes(pem)
        return key_path

    def load_private_key(self, account_key_path: str | Path):
        """加载 PEM 格式的 RSA 私钥。"""
        key_path = Path(account_key_path)
        return load_pem_private_key(key_path.read_bytes(), password=None)
```

- [ ] **Step 2: 提交**

```bash
git add certkeeper/acme_client/account.py
git commit -m "feat(acme): 实现 RSA 账户密钥生成和加载

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: ChallengeHandler 接口更新 — 添加 validation 参数

ACME 客户端需要将计算出的验证值（key authorization）传递给 challenge handler。当前接口没有这个参数，需要修改。

**Files:**
- Modify: `certkeeper/challenges/base.py`
- Modify: `certkeeper/challenges/dns01.py`
- Modify: `certkeeper/challenges/http01.py`
- Modify: `tests/test_challenges.py`

- [ ] **Step 1: 修改 `certkeeper/challenges/base.py`**

替换全部内容：

```python
"""Challenge 处理器抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from certkeeper.config import CertificateConfig


class ChallengeHandler(ABC):
    """ACME challenge 处理器基类。"""

    @abstractmethod
    def prepare(self, certificate: CertificateConfig, validation: str = "") -> None:
        """准备 challenge 校验所需资源。"""

    @abstractmethod
    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        """清理 challenge 校验相关资源。"""
```

- [ ] **Step 2: 修改 `certkeeper/challenges/dns01.py`**

替换全部内容：

```python
"""DNS-01 challenge 处理器。"""

from __future__ import annotations

from certkeeper.challenges.base import ChallengeHandler
from certkeeper.config import CertificateConfig, NamedResourceConfig
from certkeeper.dns.base import DnsProvider, ProviderRegistry


class Dns01ChallengeHandler(ChallengeHandler):
    """为校验创建并删除 DNS TXT 记录。"""

    def __init__(
        self,
        *,
        dns_provider_configs: dict[str, NamedResourceConfig],
        provider_registry: ProviderRegistry[DnsProvider],
    ) -> None:
        self.dns_provider_configs = dns_provider_configs
        self.provider_registry = provider_registry

    def prepare(self, certificate: CertificateConfig, validation: str = "") -> None:
        provider = self._resolve_provider(certificate)
        domain = certificate.domain.lstrip("*.")
        provider.create_txt_record(
            domain,
            f"_acme-challenge.{domain}",
            validation,
        )

    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        provider = self._resolve_provider(certificate)
        domain = certificate.domain.lstrip("*.")
        provider.delete_txt_record(
            domain,
            f"_acme-challenge.{domain}",
            validation,
        )

    def _resolve_provider(self, certificate: CertificateConfig) -> DnsProvider:
        if not certificate.dns_provider:
            raise ValueError("dns_provider is required for dns-01 challenges.")
        provider_config = self.dns_provider_configs[certificate.dns_provider]
        return self.provider_registry.create(provider_config)
```

注意：`domain.lstrip("*.")` 处理通配符域名（`*.example.com` → `example.com`）。

- [ ] **Step 3: 修改 `certkeeper/challenges/http01.py`**

替换全部内容：

```python
"""HTTP-01 challenge 处理器。"""

from __future__ import annotations

from pathlib import Path

from certkeeper.challenges.base import ChallengeHandler
from certkeeper.config import CertificateConfig


class Http01ChallengeHandler(ChallengeHandler):
    """为 HTTP-01 校验准备 webroot 目录和验证文件。"""

    def prepare(self, certificate: CertificateConfig, validation: str = "") -> None:
        if not certificate.http_root:
            raise ValueError("http_root is required for http-01 challenges.")

        challenge_dir = Path(certificate.http_root) / ".well-known" / "acme-challenge"
        challenge_dir.mkdir(parents=True, exist_ok=True)

        if validation and certificate.domain:
            token = validation.split(".")[0] if "." in validation else "token"
            (challenge_dir / token).write_text(validation, encoding="utf-8")

    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        # 保留目录，便于后续续期直接复用。
        _ = certificate
```

- [ ] **Step 4: 修改 `tests/test_challenges.py`**

替换全部内容：

```python
from __future__ import annotations

from certkeeper.challenges.dns01 import Dns01ChallengeHandler
from certkeeper.challenges.http01 import Http01ChallengeHandler
from certkeeper.config import CertificateConfig, NamedResourceConfig
from certkeeper.dns.base import DnsProvider, ProviderRegistry


class FakeDnsProvider(DnsProvider):
    all_records: list[tuple[str, str, str, str]] = []

    def __init__(self, config):
        super().__init__(config)

    def validate_config(self) -> list[str]:
        return []

    def create_txt_record(self, domain: str, name: str, value: str) -> None:
        self.all_records.append(("create", domain, name, value))

    def delete_txt_record(self, domain: str, name: str, value: str) -> None:
        self.all_records.append(("delete", domain, name, value))


def test_http01_handler_creates_challenge_directory(tmp_path) -> None:
    certificate = CertificateConfig(
        domain="example.com",
        san=[],
        challenge="http-01",
        dns_provider=None,
        http_root=str(tmp_path / "webroot"),
        deploy_to=[],
    )
    handler = Http01ChallengeHandler()

    handler.prepare(certificate)

    assert (tmp_path / "webroot" / ".well-known" / "acme-challenge").exists()


def test_dns01_handler_uses_named_provider_for_create_and_cleanup() -> None:
    FakeDnsProvider.all_records = []
    registry = ProviderRegistry(DnsProvider)
    registry.register("fake-dns", FakeDnsProvider)
    provider_config = NamedResourceConfig(name="aliyun", type="fake-dns", settings={})
    handler = Dns01ChallengeHandler(
        dns_provider_configs={"aliyun": provider_config},
        provider_registry=registry,
    )
    certificate = CertificateConfig(
        domain="example.com",
        san=[],
        challenge="dns-01",
        dns_provider="aliyun",
        http_root=None,
        deploy_to=[],
    )

    handler.prepare(certificate, validation="test-key-authz-value")
    handler.cleanup(certificate, validation="test-key-authz-value")

    assert FakeDnsProvider.all_records == [
        ("create", "example.com", "_acme-challenge.example.com", "test-key-authz-value"),
        ("delete", "example.com", "_acme-challenge.example.com", "test-key-authz-value"),
    ]


def test_dns01_handler_strips_wildcard_prefix() -> None:
    FakeDnsProvider.all_records = []
    registry = ProviderRegistry(DnsProvider)
    registry.register("fake-dns", FakeDnsProvider)
    provider_config = NamedResourceConfig(name="aliyun", type="fake-dns", settings={})
    handler = Dns01ChallengeHandler(
        dns_provider_configs={"aliyun": provider_config},
        provider_registry=registry,
    )
    certificate = CertificateConfig(
        domain="*.example.com",
        san=[],
        challenge="dns-01",
        dns_provider="aliyun",
        http_root=None,
        deploy_to=[],
    )

    handler.prepare(certificate, validation="abc")

    assert FakeDnsProvider.all_records[0][2] == "_acme-challenge.example.com"
```

- [ ] **Step 5: 运行测试**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/test_challenges.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: 运行全部测试确认无回归**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: 提交**

```bash
git add certkeeper/challenges/base.py certkeeper/challenges/dns01.py certkeeper/challenges/http01.py tests/test_challenges.py
git commit -m "refactor(challenges): ChallengeHandler 接口添加 validation 参数，支持真实 ACME 验证值传递

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: dns/aliyun.py — 阿里云 DNS API 真实实现

**Files:**
- Modify: `certkeeper/dns/aliyun.py`

- [ ] **Step 1: 替换 `certkeeper/dns/aliyun.py` 全部内容**

```python
"""阿里云 DNS Provider — 通过 Alidns API 管理 TXT 记录。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid

import requests

from certkeeper.dns.base import DnsProvider


class AliyunDnsProvider(DnsProvider):
    """通过阿里云 Alidns API 创建和删除 DNS TXT 记录。"""

    API_URL = "https://alidns.aliyuncs.com/"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if "access_key_id" not in self.config.settings:
            errors.append("access_key_id is required")
        if "access_key_secret" not in self.config.settings:
            errors.append("access_key_secret is required")
        return errors

    @property
    def _access_key_id(self) -> str:
        return str(self.config.settings["access_key_id"])

    @property
    def _access_key_secret(self) -> str:
        return str(self.config.settings["access_key_secret"])

    def create_txt_record(self, domain: str, name: str, value: str) -> None:
        """创建 TXT 记录并等待 DNS 生效。"""
        rr, zone = self._parse_record_name(name, domain)
        params = {
            "Action": "AddDomainRecord",
            "DomainName": zone,
            "RR": rr,
            "Type": "TXT",
            "Value": value,
        }
        self._call_api(params)
        self._wait_for_propagation(name, value)

    def delete_txt_record(self, domain: str, name: str, value: str) -> None:
        """查询并删除对应的 TXT 记录。"""
        rr, zone = self._parse_record_name(name, domain)
        record_id = self._find_record_id(zone, rr, "TXT")
        if record_id:
            params = {
                "Action": "DeleteDomainRecord",
                "RecordId": record_id,
            }
            self._call_api(params)

    def _parse_record_name(self, full_name: str, domain: str) -> tuple[str, str]:
        """解析完整记录名为 (RR, Zone)。

        例如: _acme-challenge.example.com → ("_acme-challenge", "example.com")
        """
        if full_name.endswith("." + domain):
            rr = full_name[: -(len(domain) + 1)]
        else:
            rr = full_name
        return rr, domain

    def _find_record_id(self, zone: str, rr: str, record_type: str) -> str | None:
        """查询指定 RR 和类型的记录 ID。"""
        params = {
            "Action": "DescribeDomainRecords",
            "DomainName": zone,
            "RRKeyWord": rr,
            "TypeKeyWord": record_type,
        }
        data = self._call_api(params)
        records = data.get("DomainRecords", {}).get("Record", [])
        for record in records:
            if record["RR"] == rr and record["Type"] == record_type:
                return record["RecordId"]
        return None

    def _wait_for_propagation(self, name: str, value: str, timeout: int = 60, interval: int = 5) -> None:
        """通过 Google DNS-over-HTTPS 确认 TXT 记录已生效。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = requests.get(
                    "https://dns.google/resolve",
                    params={"name": name, "type": "TXT"},
                    timeout=5,
                )
                for answer in resp.json().get("Answer", []):
                    if answer.get("data", "").strip('"') == value:
                        return
            except Exception:
                pass
            time.sleep(interval)

    def _call_api(self, business_params: dict) -> dict:
        """调用阿里云 API，自动签名。"""
        public_params = {
            "Format": "JSON",
            "Version": "2015-01-09",
            "AccessKeyId": self._access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
        }
        all_params = {**public_params, **business_params}

        sorted_params = sorted(all_params.items())
        query_string = "&".join(
            f"{self._percent_encode(str(k))}={self._percent_encode(str(v))}"
            for k, v in sorted_params
        )
        string_to_sign = "GET&%2F&" + self._percent_encode(query_string)
        signature = base64.b64encode(
            hmac.new(
                (self._access_key_secret + "&").encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        all_params["Signature"] = signature
        resp = requests.get(self.API_URL, params=all_params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _percent_encode(s: str) -> str:
        """阿里云 API 要求的 URL 编码规则。"""
        return (
            urllib.parse.quote(s, safe="")
            .replace("+", "%20")
            .replace("*", "%2A")
            .replace("%7E", "~")
        )
```

- [ ] **Step 2: 运行全部测试确认无回归**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: 提交**

```bash
git add certkeeper/dns/aliyun.py
git commit -m "feat(dns): 实现阿里云 DNS API 真实调用（AddDomainRecord/DeleteDomainRecord）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: acme_client/client.py — 完整 ACME RFC 8555 实现

**Files:**
- Modify: `certkeeper/acme_client/client.py`

这是核心任务。实现 ACME 协议的完整流程：目录发现 → 账户注册 → 创建订单 → DNS-01 验证 → CSR 生成 → 证书下载。

- [ ] **Step 1: 替换 `certkeeper/acme_client/client.py` 全部内容**

```python
"""ACME RFC 8555 客户端 — 实现 Let's Encrypt 证书申请。"""

from __future__ import annotations

import base64
import hashlib
import json
import time

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from certkeeper.acme_client.account import AcmeAccountService
from certkeeper.config import AcmeConfig, CertificateConfig
from certkeeper.core.manager import CertificateMaterial


class AcmeError(Exception):
    """ACME 协议错误。"""


class AcmeClient:
    """封装 ACME 账户与证书申请操作。"""

    def __init__(self, config: AcmeConfig) -> None:
        self.config = config
        self._directory: dict = {}
        self._nonce: str = ""
        self._kid: str = ""
        self._private_key = None

    def obtain_certificate(self, certificate: CertificateConfig, challenge_handler) -> CertificateMaterial:
        """通过 ACME 协议申请证书。完整流程：注册 → 下单 → 验证 → 签发。"""
        self._load_account_key()
        self._directory = self._fetch_directory()

        if not self._kid:
            self._kid = self._register_account()

        domains = [certificate.domain] + certificate.san
        order = self._create_order(domains)

        for auth_url in order["authorizations"]:
            self._fulfill_authorization(auth_url, certificate, challenge_handler)

        domain_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        domain_key_pem = domain_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        csr_b64 = self._generate_csr(domain_key, domains)
        order = self._finalize_order(order["finalize"], csr_b64)
        cert_pem = self._download_certificate(order["certificate"])

        return CertificateMaterial(fullchain_pem=cert_pem, private_key_pem=domain_key_pem)

    # ── 账户与密钥 ──

    def _load_account_key(self) -> None:
        svc = AcmeAccountService()
        key_path = svc.ensure_account_key(self.config.account_key)
        self._private_key = svc.load_private_key(key_path)

    # ── 目录与 nonce ──

    def _fetch_directory(self) -> dict:
        resp = requests.get(self.config.directory, timeout=30)
        resp.raise_for_status()
        self._nonce = resp.headers.get("Replay-Nonce", "")
        return resp.json()

    def _fetch_nonce(self) -> str:
        if not self._directory:
            return self._nonce
        resp = requests.head(self._directory["newNonce"], timeout=30)
        resp.raise_for_status()
        return resp.headers["Replay-Nonce"]

    # ── JWS 签名 ──

    def _jws_sign(self, url: str, payload, *, kid: str = "", jwk: dict | None = None) -> dict:
        nonce = self._nonce or self._fetch_nonce()
        protected: dict = {"alg": "RS256", "nonce": nonce, "url": url}
        if kid:
            protected["kid"] = kid
        elif jwk:
            protected["jwk"] = jwk

        protected_b64 = _b64url(json.dumps(protected, separators=(",", ":")).encode())
        payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode()) if payload is not None else ""

        sign_input = f"{protected_b64}.{payload_b64}".encode()
        signature = self._private_key.sign(sign_input, padding.PKCS1v15(), hashes.SHA256())

        return {
            "protected": protected_b64,
            "payload": payload_b64,
            "signature": _b64url(signature),
        }

    def _post(self, url: str, payload, *, kid: str = "", jwk: dict | None = None) -> requests.Response:
        body = self._jws_sign(url, payload, kid=kid, jwk=jwk)
        headers = {"Content-Type": "application/jose+json"}
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        if nonce := resp.headers.get("Replay-Nonce"):
            self._nonce = nonce
        return resp

    def _post_as_get(self, url: str) -> requests.Response:
        return self._post(url, None, kid=self._kid)

    # ── JWK 工具 ──

    def _get_jwk(self) -> dict:
        pub = self._private_key.public_key().public_numbers()
        n = pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")
        e = pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")
        return {"e": _b64url(e), "kty": "RSA", "n": _b64url(n)}

    def _jwk_thumbprint(self) -> str:
        jwk = self._get_jwk()
        jwk_json = json.dumps(jwk, separators=(",", ":"), sort_keys=True)
        return _b64url(hashlib.sha256(jwk_json.encode()).digest())

    # ── ACME 流程 ──

    def _register_account(self) -> str:
        resp = self._post(
            self._directory["newAccount"],
            {"termsOfServiceAgreed": True},
            jwk=self._get_jwk(),
        )
        if resp.status_code >= 400:
            raise AcmeError(f"Account registration failed: {resp.text}")
        return resp.headers["Location"]

    def _create_order(self, domains: list[str]) -> dict:
        identifiers = [{"type": "dns", "value": d} for d in domains]
        resp = self._post(
            self._directory["newOrder"],
            {"identifiers": identifiers},
            kid=self._kid,
        )
        if resp.status_code >= 400:
            raise AcmeError(f"Order creation failed: {resp.text}")
        return resp.json()

    def _fulfill_authorization(self, auth_url: str, certificate: CertificateConfig, handler) -> None:
        resp = self._post_as_get(auth_url)
        if resp.status_code >= 400:
            raise AcmeError(f"Get authorization failed: {resp.text}")
        auth = resp.json()

        dns_challenge = None
        for ch in auth.get("challenges", []):
            if ch.get("type") == "dns-01":
                dns_challenge = ch
                break
        if dns_challenge is None:
            raise AcmeError("No dns-01 challenge offered by the server.")

        token = dns_challenge["token"]
        key_authz = token + "." + self._jwk_thumbprint()
        dns_value = _b64url(hashlib.sha256(key_authz.encode()).digest())

        handler.prepare(certificate, validation=dns_value)

        try:
            self._post(dns_challenge["url"], {}, kid=self._kid)
            self._poll_status(dns_challenge["url"], "challenge")
        finally:
            handler.cleanup(certificate, validation=dns_value)

    def _finalize_order(self, finalize_url: str, csr_b64: str) -> dict:
        resp = self._post(finalize_url, {"csr": csr_b64}, kid=self._kid)
        if resp.status_code >= 400:
            raise AcmeError(f"Finalize failed: {resp.text}")
        order = resp.json()
        order_url = resp.headers.get("Location", finalize_url)
        return self._poll_order(order_url)

    def _poll_order(self, order_url: str, timeout: int = 60) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._post_as_get(order_url)
            if resp.status_code >= 400:
                raise AcmeError(f"Order poll failed: {resp.text}")
            order = resp.json()
            status = order.get("status")
            if status == "valid":
                return order
            if status == "invalid":
                raise AcmeError(f"Order invalid: {order}")
            time.sleep(2)
        raise AcmeError("Order finalization timed out")

    def _poll_status(self, url: str, label: str, timeout: int = 120, interval: int = 3) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._post_as_get(url)
            if resp.status_code >= 400:
                raise AcmeError(f"{label} poll failed: {resp.text}")
            data = resp.json()
            if data.get("status") == "valid":
                return
            if data.get("status") == "invalid":
                raise AcmeError(f"{label} failed: {data.get('error', {})}")
            time.sleep(interval)
        raise AcmeError(f"{label} polling timed out")

    def _download_certificate(self, cert_url: str | None) -> str:
        if not cert_url:
            raise AcmeError("No certificate URL in finalized order.")
        resp = self._post_as_get(cert_url)
        if resp.status_code >= 400:
            raise AcmeError(f"Certificate download failed: {resp.text}")
        return resp.text

    # ── CSR 生成 ──

    def _generate_csr(self, private_key, domains: list[str]) -> str:
        builder = x509.CertificateSigningRequestBuilder()
        builder = builder.subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domains[0])]))
        san = x509.SubjectAlternativeName([x509.DNSName(d) for d in domains])
        builder = builder.add_extension(san, critical=False)
        csr = builder.sign(private_key, hashes.SHA256())
        return _b64url(csr.public_bytes(serialization.Encoding.DER))


def _b64url(data: bytes) -> str:
    """Base64url 编码（无填充）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
```

- [ ] **Step 2: 运行全部测试确认无回归**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/ -v`
Expected: ALL PASS（现有测试不直接测试 client.py 内部）

- [ ] **Step 3: 提交**

```bash
git add certkeeper/acme_client/client.py
git commit -m "feat(acme): 实现 ACME RFC 8555 客户端，支持真实 Let's Encrypt 证书申请

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Staging 环境端到端验证

使用 Let's Encrypt staging 环境验证完整流程。

- [ ] **Step 1: 修改 certkeeper.yaml 使用 staging 环境**

将 `acme.directory` 临时改为：
```yaml
acme:
  directory: https://acme-staging-v02.api.letsencrypt.org/directory
```

- [ ] **Step 2: 启动 Web UI 并测试完整流程**

```bash
cd C:/Users/windy/CertKeeper
python -m certkeeper.cli web --config certkeeper.yaml
```

1. 访问 http://127.0.0.1:8088，登录
2. 通过 UI 新增一个证书配置（选择 dns-01，选择 aliyun DNS，选择部署目标）
3. 点击"执行 apply"
4. 等待 ACME 流程完成（DNS 记录创建 → 验证 → 证书签发）
5. 检查 `data/certs/{domain}/` 目录下是否有证书文件
6. Dashboard 上状态应从 "unknown-expiry" 变为显示实际天数

- [ ] **Step 3: 验证成功后将 acme.directory 改回生产环境**

```yaml
acme:
  directory: https://acme-v02.api.letsencrypt.org/directory
```
