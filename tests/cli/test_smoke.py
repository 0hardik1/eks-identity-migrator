"""CLI smoke tests via typer CliRunner — no live AWS/K8s, just argument parsing."""

from __future__ import annotations

from typer.testing import CliRunner

from eks_identity_migrator.cli import app

runner = CliRunner()


def test_root_help_lists_all_six_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.output
    for cmd in ("audit", "plan", "apply", "verify", "rollback", "migrate"):
        assert cmd in out


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "eks-identity-migrator" in result.output
    assert "0.1.0" in result.output


def test_audit_help_documents_cluster_flag() -> None:
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0
    assert "--cluster" in result.output
    assert "--out" in result.output
    # `--cluster` is now optional; help should explain the auto-detect fallback.
    assert "auto-detect" in result.output


def test_plan_help_lists_strategy_and_include_yellow() -> None:
    result = runner.invoke(app, ["plan", "--help"])
    assert result.exit_code == 0
    assert "--strategy" in result.output
    assert "--include-yellow" in result.output


def test_apply_help_lists_phase_and_dry_run() -> None:
    result = runner.invoke(app, ["apply", "--help"])
    assert result.exit_code == 0
    assert "--phase" in result.output
    assert "--dry-run" in result.output
    assert "--continue-on-error" in result.output


def test_verify_help_lists_probe() -> None:
    result = runner.invoke(app, ["verify", "--help"])
    assert result.exit_code == 0
    assert "--probe" in result.output


def test_rollback_help_lists_phase() -> None:
    result = runner.invoke(app, ["rollback", "--help"])
    assert result.exit_code == 0
    assert "--phase" in result.output
    assert "--journal" in result.output


def test_migrate_help_lists_strategy() -> None:
    result = runner.invoke(app, ["migrate", "--help"])
    assert result.exit_code == 0
    assert "--strategy" in result.output


def test_apply_invalid_phase_returns_invalid_input() -> None:
    # Invalid value for an Enum option — typer rejects with code 2.
    result = runner.invoke(app, ["apply", "--plan", "/tmp/missing.yaml", "--phase", "bogus"])
    assert result.exit_code == 2


def test_plan_invalid_strategy_handled() -> None:
    """Plan validates strategy itself before AWS — should bail with INVALID_INPUT."""
    # We can't easily test the full plan flow without AWS; this hits the validator path
    # by short-circuiting before any AWS call would happen.
    result = runner.invoke(
        app,
        [
            "plan",
            "--cluster",
            "my-cluster",
            "--strategy",
            "bogus",
        ],
    )
    # Validator returns INVALID_INPUT (2). Note: typer.Exit raises SystemExit(2).
    assert result.exit_code == 2
