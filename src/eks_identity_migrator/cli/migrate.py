"""`migrate` convenience subcommand — green-only end-to-end with verification gates.

Wire-up: cli/migrate.py → cli/runners.py::run_migrate → cli/migrate_orchestrator.py::run.
"""

from __future__ import annotations

import typer
from rich.console import Console

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.output import educational


def migrate_cmd(
    cluster: str | None = typer.Option(
        None,
        "--cluster",
        "-c",
        help="EKS cluster name. Omitted ⇒ auto-detect from current kubectl context.",
    ),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
    strategy: str = typer.Option("append", "--strategy"),
    journal: str | None = typer.Option(None, "--journal"),
    continue_on_error: bool = typer.Option(False, "--continue-on-error"),
) -> None:
    """Green-only fast path: trust → association → verify → cleanup."""
    from eks_identity_migrator.cli._resolve import resolve_cluster
    from eks_identity_migrator.cli._validators import validate_strategy
    from eks_identity_migrator.cli.runners import run_migrate

    validate_strategy(strategy)
    resolved_cluster, resolved_region = resolve_cluster(cluster, region)

    Console(stderr=True).print(educational.migrate_intro())

    code = run_migrate(
        cluster=resolved_cluster,
        region=resolved_region,
        profile=profile,
        strategy=strategy,
        journal=journal,
        continue_on_error=continue_on_error,
    )
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="migrate", help="Convenience: green-only end-to-end with verify gates.")(
        migrate_cmd
    )
