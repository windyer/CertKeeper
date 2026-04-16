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
