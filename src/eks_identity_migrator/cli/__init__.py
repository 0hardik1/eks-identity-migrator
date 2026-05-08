"""Typer root + global options + subcommand registration."""

from __future__ import annotations

import typer

from eks_identity_migrator.cli import apply as apply_cmd_module
from eks_identity_migrator.cli import audit as audit_cmd_module
from eks_identity_migrator.cli import migrate as migrate_cmd_module
from eks_identity_migrator.cli import plan as plan_cmd_module
from eks_identity_migrator.cli import rollback as rollback_cmd_module
from eks_identity_migrator.cli import verify as verify_cmd_module
from eks_identity_migrator.logging import setup_logging
from eks_identity_migrator.version import __version__

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Audit IRSA usage and migrate to EKS Pod Identity.",
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"eks-identity-migrator {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    no_color: bool = typer.Option(False, "--no-color", help="Disable ANSI color in output."),
    verbose: int = typer.Option(0, "-v", "--verbose", count=True, help="Increase verbosity."),
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Global options shared across all subcommands."""
    setup_logging(verbose, no_color=no_color)


# Register subcommands. Per-command global flags (cluster/region/etc.) live on each subcommand
# rather than the root callback because typer binds them per-command and that matches spec §4.
audit_cmd_module.register(app)
plan_cmd_module.register(app)
apply_cmd_module.register(app)
verify_cmd_module.register(app)
rollback_cmd_module.register(app)
migrate_cmd_module.register(app)


__all__ = ["app"]
