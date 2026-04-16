from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from certkeeper.core.store import Store


def _build_certificate_pem(common_name: str, expires_in_days: int = 30) -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=expires_in_days))
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return cert_pem, key_pem


def test_store_persists_certificate_and_state(tmp_path) -> None:
    store = Store(tmp_path)
    cert_pem, key_pem = _build_certificate_pem("example.com", expires_in_days=15)

    written = store.save_certificate("example.com", cert_pem, key_pem)
    store.record_result(
        domain="example.com",
        expires_at=datetime.now(UTC) + timedelta(days=15),
        renewed_at=datetime.now(UTC),
        deploy_results={"nginx-web": "success"},
    )

    status = store.get_certificate_status("example.com")

    assert written.fullchain_path.exists()
    assert written.private_key_path.exists()
    assert status.exists is True
    assert status.expires_at is not None
    assert status.days_until_expiry is not None
    assert status.days_until_expiry <= 15
    assert status.last_deploy_results["nginx-web"] == "success"
