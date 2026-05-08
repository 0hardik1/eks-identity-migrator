"""`rollback --phase ...` subcommand."""

from __future__ import annotations

import typer

from eks_identity_migrator.cli.apply import Phase
from eks_identity_migrator.cli.exit_codes import ExitCode


def rollback_cmd(
    journal: str = typer.Option(..., "--journal", help="Path to journal NDJSON."),
    phase: Phase = typer.Option(..., "--phase", case_sensitive=False),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Reverse a phase using the journal."""
    from eks_identity_migrator.cli.runners import run_rollback

    code = run_rollback(journal=journal, phase=phase.value, region=region, profile=profile)
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="rollback", help="Reverse a phase using the journal.")(rollback_cmd)
