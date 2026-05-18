"""`audit` subcommand — read-only inventory and risk classification.

Wire-up: cli/audit.py → cli/runners.py::run_audit → audit/__init__.py::run
→ audit/entry.py::run. The CLI file is intentionally thin: parse + resolve
flags, then call the orchestrator.
"""

from __future__ import annotations

import typer
from rich.console import Console

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.output import educational


def audit_cmd(
    cluster: str | None = typer.Option(
        None,
        "--cluster",
        "-c",
        help="EKS cluster name. Omitted ⇒ auto-detect from current kubectl context.",
    ),
    region: str | None = typer.Option(None, "--region", "-r", help="AWS region."),
    profile: str | None = typer.Option(None, "--profile", help="AWS profile."),
    out: str | None = typer.Option(None, "--out", help="Write the inventory to this file."),
) -> None:
    """Read-only inventory and classification of IRSA-using ServiceAccounts."""
    from eks_identity_migrator.cli._resolve import resolve_cluster
    from eks_identity_migrator.cli.runners import run_audit

    resolved_cluster, resolved_region = resolve_cluster(cluster, region)

    err = Console(stderr=True)
    err.print(educational.audit_intro())

    code = run_audit(cluster=resolved_cluster, region=resolved_region, profile=profile, out=out)

    if code == ExitCode.OK:
        err.print(educational.audit_outro())

    raise typer.Exit(code=int(code if isinstance(code, ExitCode) else ExitCode.OK))


def register(app: typer.Typer) -> None:
    app.command(name="audit", help="Read-only IRSA inventory + classification.")(audit_cmd)
