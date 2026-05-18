"""`plan` subcommand — generate plan.yaml from an audit.

Wire-up: cli/plan.py → cli/runners.py::run_plan → plan/__init__.py::run
→ plan/entry.py::run.
"""

from __future__ import annotations

import typer
from rich.console import Console

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.output import educational


def plan_cmd(
    cluster: str | None = typer.Option(
        None,
        "--cluster",
        "-c",
        help="EKS cluster name. Omitted ⇒ auto-detect from current kubectl context.",
    ),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
    strategy: str = typer.Option("append", "--strategy", help="append|replace"),
    include_yellow: bool = typer.Option(False, "--include-yellow"),
    out: str = typer.Option("plan.yaml", "--out"),
) -> None:
    """Generate a migration plan."""
    from eks_identity_migrator.cli._resolve import resolve_cluster
    from eks_identity_migrator.cli._validators import validate_strategy
    from eks_identity_migrator.cli.runners import run_plan

    validate_strategy(strategy)
    resolved_cluster, resolved_region = resolve_cluster(cluster, region)

    Console(stderr=True).print(educational.plan_intro(strategy=strategy))

    code = run_plan(
        cluster=resolved_cluster,
        region=resolved_region,
        profile=profile,
        strategy=strategy,
        include_yellow=include_yellow,
        out=out,
    )
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="plan", help="Generate a migration plan.")(plan_cmd)
