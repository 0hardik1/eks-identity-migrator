"""`apply --phase ...` subcommand.

Wire-up: cli/apply.py → cli/runners.py::run_apply → apply/__init__.py::run.
Phase is a typer Enum so an invalid value gets rejected by typer itself
(exit code 2) before any AWS call is made.
"""

from __future__ import annotations

from enum import StrEnum

import typer
from rich.console import Console

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.output import educational


class Phase(StrEnum):
    TRUST = "trust"
    ASSOCIATION = "association"
    CLEANUP = "cleanup"


def apply_cmd(
    plan: str = typer.Option(..., "--plan", help="Path to plan.yaml."),
    phase: Phase = typer.Option(..., "--phase", case_sensitive=False),
    dry_run: bool = typer.Option(False, "--dry-run"),
    continue_on_error: bool = typer.Option(False, "--continue-on-error"),
    journal: str | None = typer.Option(None, "--journal"),
    remove_oidc_trust: bool = typer.Option(
        False, "--remove-oidc-trust", help="Cleanup phase only: also strip OIDC statement."
    ),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Execute one migration phase."""
    from eks_identity_migrator.cli.runners import run_apply

    Console(stderr=True).print(educational.apply_phase_intro(phase=phase.value))

    code = run_apply(
        plan=plan,
        phase=phase.value,
        dry_run=dry_run,
        continue_on_error=continue_on_error,
        journal=journal,
        remove_oidc_trust=remove_oidc_trust,
        region=region,
        profile=profile,
    )
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="apply", help="Execute one migration phase.")(apply_cmd)
