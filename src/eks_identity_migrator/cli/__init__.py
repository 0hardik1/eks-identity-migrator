"""Typer root + global options + subcommand registration.

This package only handles argument parsing and wiring. The actual business
logic lives one layer down in `cli/runners.py` (lazy-imported per subcommand
to keep `--help` fast).

Wire-up trace per command:
    cli/audit.py    → cli/runners.py::run_audit    → audit/entry.py
    cli/plan.py     → cli/runners.py::run_plan     → plan/entry.py
    cli/apply.py    → cli/runners.py::run_apply    → apply/__init__.py
    cli/verify.py   → cli/runners.py::run_verify   → verify/__init__.py
    cli/rollback.py → cli/runners.py::run_rollback → rollback/__init__.py
    cli/migrate.py  → cli/runners.py::run_migrate  → cli/migrate_orchestrator.py
"""

from __future__ import annotations

import typer

from eks_identity_migrator.cli import apply as apply_cmd_module
from eks_identity_migrator.cli import audit as audit_cmd_module
from eks_identity_migrator.cli import migrate as migrate_cmd_module
from eks_identity_migrator.cli import plan as plan_cmd_module
from eks_identity_migrator.cli import rollback as rollback_cmd_module
from eks_identity_migrator.cli import verify as verify_cmd_module
from eks_identity_migrator.logging import setup_logging
from eks_identity_migrator.output import educational
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
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress the educational intro/outro panels."
    ),
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Global options shared across all subcommands."""
    setup_logging(verbose, no_color=no_color)
    educational.set_quiet(quiet)


# Register subcommands. Per-command flags (cluster/region/etc.) live on each subcommand
# rather than the root callback because typer binds them per-command and that matches spec §4.
audit_cmd_module.register(app)
plan_cmd_module.register(app)
apply_cmd_module.register(app)
verify_cmd_module.register(app)
rollback_cmd_module.register(app)
migrate_cmd_module.register(app)


__all__ = ["app"]
