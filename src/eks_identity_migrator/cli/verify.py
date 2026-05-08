"""`verify` subcommand — confirm credential source per pod."""

from __future__ import annotations

import typer

from eks_identity_migrator.cli.exit_codes import ExitCode


def verify_cmd(
    plan: str = typer.Option(..., "--plan"),
    probe: bool = typer.Option(False, "--probe", help="kubectl exec aws sts get-caller-identity."),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Verify migration result."""
    from eks_identity_migrator.cli.runners import run_verify

    code = run_verify(plan=plan, probe=probe, region=region, profile=profile)
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="verify", help="Verify post-migration credential source.")(verify_cmd)
