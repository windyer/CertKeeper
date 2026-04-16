"""本地证书与状态存储。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography import x509


@dataclass(slots=True)
class WrittenCertificate:
    fullchain_path: Path
    private_key_path: Path


@dataclass(slots=True)
class CertificateStatus:
    domain: str
    exists: bool
    fullchain_path: Path
    private_key_path: Path
    expires_at: datetime | None
    days_until_expiry: int | None
    last_renewed_at: datetime | None
    last_deploy_results: dict[str, str] = field(default_factory=dict)


class Store:
    """在本地文件系统中持久化证书与状态。"""

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)
        self.certs_path = self.base_path / "certs"
        self.state_path = self.base_path / "state.json"
        self.account_key_path = self.base_path / "account.key"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.certs_path.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.state_path.write_text("{}", encoding="utf-8")

    def certificate_dir(self, domain: str) -> Path:
        return self.certs_path / domain

    def save_certificate(self, domain: str, fullchain_pem: str, private_key_pem: str) -> WrittenCertificate:
        cert_dir = self.certificate_dir(domain)
        cert_dir.mkdir(parents=True, exist_ok=True)

        fullchain_path = cert_dir / "fullchain.pem"
        private_key_path = cert_dir / "privkey.pem"
        fullchain_path.write_text(fullchain_pem, encoding="utf-8")
        private_key_path.write_text(private_key_pem, encoding="utf-8")

        return WrittenCertificate(fullchain_path=fullchain_path, private_key_path=private_key_path)

    def load_state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    def record_result(
        self,
        domain: str,
        *,
        expires_at: datetime | None = None,
        renewed_at: datetime | None = None,
        deploy_results: dict[str, str] | None = None,
    ) -> None:
        state = self.load_state()
        domain_state = dict(state.get(domain, {}))

        if expires_at is not None:
            domain_state["expires_at"] = expires_at.astimezone(UTC).isoformat()
        if renewed_at is not None:
            domain_state["renewed_at"] = renewed_at.astimezone(UTC).isoformat()
        if deploy_results is not None:
            domain_state["deploy_results"] = deploy_results

        state[domain] = domain_state
        self.save_state(state)

    def get_certificate_status(self, domain: str) -> CertificateStatus:
        cert_dir = self.certificate_dir(domain)
        fullchain_path = cert_dir / "fullchain.pem"
        private_key_path = cert_dir / "privkey.pem"
        exists = fullchain_path.exists() and private_key_path.exists()

        state = self.load_state().get(domain, {})
        expires_at = self._read_certificate_expiry(fullchain_path) if exists else None
        if expires_at is None:
            expires_at = _parse_datetime(state.get("expires_at"))
        last_renewed_at = _parse_datetime(state.get("renewed_at"))
        deploy_results = state.get("deploy_results", {})

        days_until_expiry: int | None = None
        if expires_at is not None:
            seconds = (expires_at - datetime.now(UTC)).total_seconds()
            days_until_expiry = max(int(seconds // 86400), 0)

        return CertificateStatus(
            domain=domain,
            exists=exists,
            fullchain_path=fullchain_path,
            private_key_path=private_key_path,
            expires_at=expires_at,
            days_until_expiry=days_until_expiry,
            last_renewed_at=last_renewed_at,
            last_deploy_results={str(key): str(value) for key, value in deploy_results.items()},
        )

    def _read_certificate_expiry(self, cert_path: Path) -> datetime | None:
        try:
            certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        except (ValueError, OSError):
            return None

        not_valid_after = certificate.not_valid_after_utc
        return not_valid_after.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value)).astimezone(UTC)
