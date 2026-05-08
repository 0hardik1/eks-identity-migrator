"""Thin orchestrator functions called from each cli/<cmd>.py.

Keeping these in one module makes it easy to test the wiring without invoking
the typer app. Real implementations land here as the corresponding modules
(audit, plan, apply, verify, rollback) come online during the build.
"""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run_audit(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    out: str | None,
) -> ExitCode:
    from eks_identity_migrator.audit import run as audit_run

    return audit_run(cluster=cluster, region=region, profile=profile, out=out)


def run_plan(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    strategy: str,
    include_yellow: bool,
    out: str,
) -> ExitCode:
    from eks_identity_migrator.plan import run as plan_run

    return plan_run(
        cluster=cluster,
        region=region,
        profile=profile,
        strategy=strategy,
        include_yellow=include_yellow,
        out=out,
    )


def run_apply(
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
    from eks_identity_migrator.apply import run as apply_run

    return apply_run(
        plan=plan,
        phase=phase,
        dry_run=dry_run,
        continue_on_error=continue_on_error,
        journal=journal,
        remove_oidc_trust=remove_oidc_trust,
        region=region,
        profile=profile,
    )


def run_verify(
    *,
    plan: str,
    probe: bool,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.verify import run as verify_run

    return verify_run(plan=plan, probe=probe, region=region, profile=profile)


def run_rollback(
    *,
    journal: str,
    phase: str,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.rollback import run as rollback_run

    return rollback_run(journal=journal, phase=phase, region=region, profile=profile)


def run_migrate(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    strategy: str,
    journal: str | None,
    continue_on_error: bool,
) -> ExitCode:
    from eks_identity_migrator.cli import migrate_orchestrator

    return migrate_orchestrator.run(
        cluster=cluster,
        region=region,
        profile=profile,
        strategy=strategy,
        journal=journal,
        continue_on_error=continue_on_error,
    )
