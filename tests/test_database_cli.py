from typer.testing import CliRunner

from proof_agent.delivery.cli import app


def test_database_cli_exposes_explicit_expand_only_commands() -> None:
    result = CliRunner().invoke(app, ["database", "--help"])

    assert result.exit_code == 0
    assert "current" in result.stdout
    assert "check" in result.stdout
    assert "upgrade" in result.stdout
    assert "downgrade" not in result.stdout
