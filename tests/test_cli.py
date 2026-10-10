from typer.testing import CliRunner

from sahi.cli import app

runner = CliRunner()


def test_cli_exposes_required_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("probe", "locations", "check", "number", "sweep", "fixtures", "account"):
        assert command in result.stdout


def test_check_rejects_unknown_seed_brand_without_spending_searches():
    result = runner.invoke(app, ["check", "--brand", "missing", "--city", "Mumbai"])
    assert result.exit_code != 0
    assert "Unknown brand" in result.stdout
