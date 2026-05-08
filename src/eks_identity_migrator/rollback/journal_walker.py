"""Walk a journal in reverse and apply inverses (spec §7.6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from eks_identity_migrator.aws.eks import EksClient
from eks_identity_migrator.aws.iam import IamClient
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.journal.reader import iter_journal_reverse
from eks_identity_migrator.k8s.client import K8sClient
from eks_identity_migrator.rollback.inverses import (
    invert_create_pod_identity_association,
    invert_iam_update_assume_role_policy,
    invert_remove_sa_annotation,
)
from eks_identity_migrator.types.journal import JournalOp, JournalStatus


@dataclass
class RollbackResult:
    inverted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def exit_code(self) -> ExitCode:
        if self.failed:
            return ExitCode.PARTIAL if self.inverted else ExitCode.AWS_ERROR
        return ExitCode.OK


# Map a CLI --phase value to the JournalOps that phase wrote.
PHASE_OPS: dict[str, set[JournalOp]] = {
    "trust": {JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY},
    "association": {JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION},
    "cleanup": {JournalOp.K8S_REMOVE_SA_ANNOTATION},
}


def rollback(
    journal_path: str,
    *,
    phase: str | None,
    iam: IamClient,
    eks: EksClient,
    k8s: K8sClient,
) -> RollbackResult:
    """Walk journal in reverse and dispatch the inverse for each successful op.

    `phase=None` rolls back every op type. Otherwise restrict to the ops the
    given phase emitted.
    """
    target_ops: set[JournalOp] | None
    if phase is None:
        target_ops = None
    else:
        if phase not in PHASE_OPS:
            raise ValueError(f"unknown phase: {phase}")
        target_ops = PHASE_OPS[phase]

    result = RollbackResult()
    for entry in iter_journal_reverse(journal_path):
        if entry.status != JournalStatus.SUCCESS:
            continue
        if target_ops and entry.op not in target_ops:
            continue
        try:
            if entry.op == JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY:
                invert_iam_update_assume_role_policy(entry, iam=iam)
            elif entry.op == JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION:
                invert_create_pod_identity_association(entry, eks=eks)
            elif entry.op == JournalOp.K8S_REMOVE_SA_ANNOTATION:
                invert_remove_sa_annotation(entry, k8s=k8s)
            else:
                result.skipped += 1
                continue
            result.inverted += 1
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"{entry.sa}: {exc}")
    return result
