"""Discovery + classification entry point."""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    out: str | None,
) -> ExitCode:
    """Implemented in audit/entry.py once the audit module is wired (build step 9)."""
    from eks_identity_migrator.audit.entry import run as _run

    return _run(cluster=cluster, region=region, profile=profile, out=out)
