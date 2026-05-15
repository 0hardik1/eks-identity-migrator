"""`rollback --phase ...` subcommand.

Wire-up: cli/rollback.py → cli/runners.py::run_rollback → rollback/__init__.py::run.
"""

from __future__ import annotations

import typer
from rich.console import Console

from eks_identity_migrator.cli.apply import Phase
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.output import educational


def rollback_cmd(
    journal: str = typer.Option(..., "--journal", help="Path to journal NDJSON."),
    phase: Phase = typer.Option(..., "--phase", case_sensitive=False),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Reverse a phase using the journal."""
    from eks_identity_migrator.cli.runners import run_rollback

    Console(stderr=True).print(educational.rollback_intro())

    code = run_rollback(journal=journal, phase=phase.value, region=region, profile=profile)
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="rollback", help="Reverse a phase using the journal.")(rollback_cmd)
