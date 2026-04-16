from click.testing import CliRunner

from certkeeper.cli import main


def test_daemon_install_prints_service_command(tmp_path) -> None:
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["--config", str(config_file), "daemon", "--install"])

    assert result.exit_code == 0
    assert "Service install command:" in result.output
