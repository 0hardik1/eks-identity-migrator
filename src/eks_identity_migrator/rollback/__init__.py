"""Rollback entry point."""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    journal: str,
    phase: str,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.rollback.entry import run as _run

    return _run(journal=journal, phase=phase, region=region, profile=profile)
