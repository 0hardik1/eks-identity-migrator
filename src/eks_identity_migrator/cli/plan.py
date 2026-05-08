"""`plan` subcommand — generate plan.yaml from an audit."""

from __future__ import annotations

import typer

from eks_identity_migrator.cli.exit_codes import ExitCode


def plan_cmd(
    cluster: str = typer.Option(..., "--cluster", "-c"),
    region: str | None = typer.Option(None, "--region", "-r"),
    profile: str | None = typer.Option(None, "--profile"),
    strategy: str = typer.Option("append", "--strategy", help="append|replace"),
    include_yellow: bool = typer.Option(False, "--include-yellow"),
    out: str = typer.Option("plan.yaml", "--out"),
) -> None:
    """Generate a migration plan."""
    from eks_identity_migrator.cli.runners import run_plan

    code = run_plan(
        cluster=cluster,
        region=region,
        profile=profile,
        strategy=strategy,
        include_yellow=include_yellow,
        out=out,
    )
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="plan", help="Generate a migration plan.")(plan_cmd)
