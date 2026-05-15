"""Tests for cli/_validators.py — shared CLI input validators."""

from __future__ import annotations

import pytest
import typer

from eks_identity_migrator.cli._validators import validate_strategy


class TestValidateStrategy:
    @pytest.mark.parametrize("value", ["append", "replace"])
    def test_accepts_valid_strategies(self, value: str) -> None:
        assert validate_strategy(value) == value

    @pytest.mark.parametrize("value", ["", "APPEND", "Append", "merge", "bogus", "  "])
    def test_rejects_anything_else(self, value: str) -> None:
        with pytest.raises(typer.BadParameter) as exc_info:
            validate_strategy(value)
        # The message should educate, not just say "invalid".
        msg = str(exc_info.value)
        assert "append" in msg
        assert "replace" in msg

    def test_error_mentions_param_hint(self) -> None:
        with pytest.raises(typer.BadParameter) as exc_info:
            validate_strategy("bogus")
        assert exc_info.value.param_hint == "--strategy"


def test_plan_with_invalid_strategy_exits_with_invalid_input() -> None:
    """Integration: invalid --strategy via CLI returns exit code 2."""
    from typer.testing import CliRunner

    from eks_identity_migrator.cli import app

    result = CliRunner().invoke(app, ["plan", "--cluster", "x", "--strategy", "bogus"])
    assert result.exit_code == 2
    # The user should see something about valid strategies in the help/error.
    assert "append" in result.output.lower() or "replace" in result.output.lower()


def test_migrate_with_invalid_strategy_exits_with_invalid_input() -> None:
    from typer.testing import CliRunner

    from eks_identity_migrator.cli import app

    result = CliRunner().invoke(app, ["migrate", "--cluster", "x", "--strategy", "bogus"])
    assert result.exit_code == 2
