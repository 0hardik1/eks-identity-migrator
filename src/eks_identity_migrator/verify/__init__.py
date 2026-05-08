"""Verify entry point."""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    plan: str,
    probe: bool,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.verify.entry import run as _run

    return _run(plan=plan, probe=probe, region=region, profile=profile)
