"""Common apply runner — journal wrapping, dry-run, continue-on-error.

Each handler returns a `PreparedStep` describing the intended op + state
*without* performing the side effect. The runner then either calls
`prepared.apply()` (real run) or skips it (dry-run) — this keeps `--dry-run`
guaranteed-side-effect-free even if a handler is buggy.
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

        try:
            prepared = handler(step)
        except Exception as exc:
            journal.write(
                JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
                JournalStatus.FAILURE,
                step.sa,
                role_arn=step.role_arn,
                cluster=plan.cluster.name,
                error=str(exc),
            )
            result.failed += 1
            assert result.errors is not None
            result.errors.append(f"{step.sa}: {exc}")
            if not continue_on_error:
                return result
            continue

        # Pre-existing failure (e.g., handler discovered the role doesn't exist).
        if prepared.apply is None and prepared.error is not None:
            journal.write(
                prepared.op,
                JournalStatus.FAILURE,
                step.sa,
                role_arn=step.role_arn,
                cluster=plan.cluster.name,
                before=prepared.before,
                after=prepared.after,
                error=prepared.error,
            )
            result.failed += 1
            assert result.errors is not None
            result.errors.append(f"{step.sa}: {prepared.error}")
            if not continue_on_error:
                return result
            continue

        # Already-applied — handler decided no-op.
        if prepared.apply is None:
            journal.write(
                prepared.op,
                JournalStatus.SKIPPED,
                step.sa,
                role_arn=step.role_arn,
                cluster=plan.cluster.name,
                before=prepared.before,
                after=prepared.after,
                note=prepared.note or "already-applied",
            )
            result.skipped += 1
            continue

        if dry_run:
            journal.write(
                prepared.op,
                JournalStatus.PENDING,
                step.sa,
                role_arn=step.role_arn,
                cluster=plan.cluster.name,
                before=prepared.before,
                after=prepared.after,
                note="dry-run",
            )
            result.succeeded += 1
            continue

        try:
            prepared.apply()
        except Exception as exc:
            journal.write(
                prepared.op,
                JournalStatus.FAILURE,
                step.sa,
                role_arn=step.role_arn,
                cluster=plan.cluster.name,
                before=prepared.before,
                after=prepared.after,
                error=str(exc),
            )
            result.failed += 1
            assert result.errors is not None
            result.errors.append(f"{step.sa}: {exc}")
            if not continue_on_error:
                return result
            continue

        journal.write(
            prepared.op,
            JournalStatus.SUCCESS,
            step.sa,
            role_arn=step.role_arn,
            cluster=plan.cluster.name,
            before=prepared.before,
            after=prepared.after,
            note=prepared.note,
        )
        result.succeeded += 1

    return result
