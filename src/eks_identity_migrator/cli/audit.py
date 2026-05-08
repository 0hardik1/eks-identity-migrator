"""`audit` subcommand — read-only inventory and risk classification."""

from __future__ import annotations

import typer

from eks_identity_migrator.cli.exit_codes import ExitCode


def audit_cmd(
    cluster: str = typer.Option(..., "--cluster", "-c", help="EKS cluster name."),
    region: str | None = typer.Option(None, "--region", "-r", help="AWS region."),
    profile: str | None = typer.Option(None, "--profile", help="AWS profile."),
    out: str | None = typer.Option(None, "--out", help="Write the inventory to this file."),
) -> None:
    """Read-only inventory and classification of IRSA-using ServiceAccounts."""
    # Wired in cli/audit.py:run_audit during step 9 of the build. Keep CLI thin.
    from eks_identity_migrator.cli.runners import run_audit

    code = run_audit(cluster=cluster, region=region, profile=profile, out=out)
    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="audit", help="Read-only IRSA inventory + classification.")(audit_cmd)
