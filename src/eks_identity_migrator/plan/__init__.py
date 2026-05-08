"""Plan generation entry point."""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    strategy: str,
    include_yellow: bool,
    out: str,
) -> ExitCode:
    from eks_identity_migrator.plan.entry import run as _run

    return _run(
        cluster=cluster,
        region=region,
        profile=profile,
        strategy=strategy,
        include_yellow=include_yellow,
        out=out,
    )
