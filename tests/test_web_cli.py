from __future__ import annotations

from click.testing import CliRunner

from certkeeper.cli import main
from certkeeper.web.auth import hash_password


def test_web_command_starts_uvicorn_with_expected_host_and_port(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "super-secret")
    password_hash = hash_password("admin123", salt="testsalt", iterations=1000)
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "web_ui:",
                "  enabled: true",
                "  host: 0.0.0.0",
                "  port: 9090",
                "  session_secret: ${WEB_SESSION_SECRET}",
                "  admin_username: admin",
                f"  admin_password_hash: {password_hash}",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_run(app, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("certkeeper.cli.uvicorn.run", fake_run)

    result = CliRunner().invoke(main, ["--config", str(config_file), "web"])

    assert result.exit_code == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9090
