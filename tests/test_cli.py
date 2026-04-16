from click.testing import CliRunner

from certkeeper.cli import main


def test_cli_registers_expected_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    for command in (
        "init",
        "register",
        "apply",
        "renew",
        "deploy",
        "list",
        "check",
        "daemon",
    ):
        assert command in result.output


def test_list_command_accepts_config_option(tmp_path) -> None:
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

    result = CliRunner().invoke(main, ["--config", str(config_file), "list"])

    assert result.exit_code == 0
    assert "No certificates configured." in result.output
