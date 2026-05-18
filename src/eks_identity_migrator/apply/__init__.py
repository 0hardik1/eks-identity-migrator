"""Apply one migration phase to AWS / K8s state.

The package is split into a generic :mod:`runner` (handles journaling,
dry-run, continue-on-error) plus three thin handlers — :mod:`trust`,
:mod:`association`, :mod:`cleanup` — one per phase. Every side effect is
wrapped by ``runner._record`` so :mod:`rollback` can replay the journal in
reverse later.

Run order is mandatory: trust must succeed before association, and verify
should be clean before cleanup. The CLI enforces this only by convention —
each phase is its own subcommand invocation.
"""

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
