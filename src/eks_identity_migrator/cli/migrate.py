"""`migrate` convenience subcommand — green-only end-to-end with verification gates."""

from __future__ import annotations

import typer

from eks_identity_migrator.cli.exit_codes import ExitCode


def migrate_cmd(
    cluster: str = typer.Option(..., "--cluster", "-c"),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
    strategy: str = typer.Option("append", "--strategy"),
    journal: str | None = typer.Option(None, "--journal"),
    continue_on_error: bool = typer.Option(False, "--continue-on-error"),
) -> None:
    """Green-only fast path: trust → association → verify → cleanup."""
    from eks_identity_migrator.cli.runners import run_migrate

    code = run_migrate(
        cluster=cluster,
        region=region,
        profile=profile,
        strategy=strategy,
        journal=journal,
        continue_on_error=continue_on_error,
    )
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(
        name="migrate", help="Convenience: green-only end-to-end with verify gates."
    )(migrate_cmd)
