"""Apply phase dispatch."""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    plan: str,
    phase: str,
    dry_run: bool,
    continue_on_error: bool,
    journal: str | None,
    remove_oidc_trust: bool,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.apply.entry import run as _run

    return _run(
        plan=plan,
        phase=phase,
        dry_run=dry_run,
        continue_on_error=continue_on_error,
        journal=journal,
        remove_oidc_trust=remove_oidc_trust,
        region=region,
        profile=profile,
    )
