"""Common apply runner — journal wrapping, dry-run, continue-on-error.

Each phase (trust / association / cleanup) provides a *handler* that, given
a :class:`PlanStep`, returns a :class:`PreparedStep` describing what would
happen *without* performing the side effect. The runner then either calls
``prepared.apply()`` (real run) or skips it (dry-run). This split keeps
``--dry-run`` guaranteed-side-effect-free even if a handler is buggy.

Every outcome (skipped, dry-run, success, failure) gets one journal entry
written via the local ``_record`` helper — that's how rollback works later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.journal.writer import JournalWriter
from eks_identity_migrator.types.journal import JournalOp, JournalStatus
from eks_identity_migrator.types.plan import Plan, PlanStep


@dataclass
class ApplyResult:
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def exit_code(self) -> ExitCode:
        if self.failed:
            return ExitCode.PARTIAL if self.succeeded else ExitCode.AWS_ERROR
        return ExitCode.OK


@dataclass
class PreparedStep:
    """An apply operation that has been computed but not yet executed."""

    op: JournalOp
    before: dict[str, object]
    after: dict[str, object]
    # When None, the step is already-applied (handler decided no work needed).
    apply: Callable[[], None] | None = None
    # When set without `apply`, marks the step as a pre-existing failure (e.g., role missing).
    error: str | None = None
    note: str | None = None


StepHandler = Callable[[PlanStep], PreparedStep]


def _record(
    journal: JournalWriter,
    plan: Plan,
    step: PlanStep,
    op: JournalOp,
    status: JournalStatus,
    *,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    error: str | None = None,
    note: str | None = None,
) -> None:
    """Write one journal entry for ``step``. All six runner outcomes funnel here."""
    journal.write(
        op,
        status,
        step.sa,
        role_arn=step.role_arn,
        cluster=plan.cluster.name,
        before=before,
        after=after,
        error=error,
        note=note,
    )


def _add_failure(result: ApplyResult, step: PlanStep, message: str) -> None:
    result.failed += 1
    assert result.errors is not None
    result.errors.append(f"{step.sa}: {message}")


def run_phase(
    plan: Plan,
    *,
    journal: JournalWriter,
    handler: StepHandler,
    dry_run: bool,
    continue_on_error: bool,
) -> ApplyResult:
    result = ApplyResult()
    for step in plan.steps:
        if step.skip:
            result.skipped += 1
            continue

        # 1. Run the handler. Unexpected exceptions become a generic FAILURE.
        try:
            prepared = handler(step)
        except Exception as exc:
            _record(
                journal,
                plan,
                step,
                JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
                JournalStatus.FAILURE,
                error=str(exc),
            )
            _add_failure(result, step, str(exc))
            if not continue_on_error:
                return result
            continue

        # 2. Handler decided this step is a pre-existing failure (e.g., role missing).
        if prepared.apply is None and prepared.error is not None:
            _record(
                journal,
                plan,
                step,
                prepared.op,
                JournalStatus.FAILURE,
                before=prepared.before,
                after=prepared.after,
                error=prepared.error,
            )
            _add_failure(result, step, prepared.error)
            if not continue_on_error:
                return result
            continue

        # 3. Handler decided nothing to do (already at desired state).
        if prepared.apply is None:
            _record(
                journal,
                plan,
                step,
                prepared.op,
                JournalStatus.SKIPPED,
                before=prepared.before,
                after=prepared.after,
                note=prepared.note or "already-applied",
            )
            result.skipped += 1
            continue

        # 4. Dry-run — record what we *would* do, but never call apply().
        if dry_run:
            _record(
                journal,
                plan,
                step,
                prepared.op,
                JournalStatus.PENDING,
                before=prepared.before,
                after=prepared.after,
                note="dry-run",
            )
            result.succeeded += 1
            continue

        # 5. Real run — call apply(), translating exceptions into FAILURE.
        try:
            prepared.apply()
        except Exception as exc:
            _record(
                journal,
                plan,
                step,
                prepared.op,
                JournalStatus.FAILURE,
                before=prepared.before,
                after=prepared.after,
                error=str(exc),
            )
            _add_failure(result, step, str(exc))
            if not continue_on_error:
                return result
            continue

        # 6. Success.
        _record(
            journal,
            plan,
            step,
            prepared.op,
            JournalStatus.SUCCESS,
            before=prepared.before,
            after=prepared.after,
            note=prepared.note,
        )
        result.succeeded += 1

    return result
