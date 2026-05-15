"""Reverse a phase by replaying the journal in reverse.

The journal is the only source of truth for rollback — we never read AWS or
K8s state directly. :mod:`journal_walker` walks the NDJSON file backwards,
finds every successful entry for the requested phase, and hands it to one
of the per-op inverse functions in :mod:`inverses` (one for each
``JournalOp``).

Because every ``apply`` operation records ``before``/``after`` state in the
journal entry, the inverse never has to recompute it — it just restores
``before``. That's why apply journaling is non-negotiable (CLAUDE.md hard
rule §3).
"""

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
