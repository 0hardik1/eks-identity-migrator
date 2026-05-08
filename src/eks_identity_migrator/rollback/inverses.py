"""Per-op inverse implementations (spec §7.6)."""

from __future__ import annotations

from eks_identity_migrator.aws.eks import EksClient
from eks_identity_migrator.aws.iam import IamClient, role_name_from_arn
from eks_identity_migrator.k8s.client import K8sClient
from eks_identity_migrator.types.journal import JournalEntry, JournalOp


class CorruptedJournalError(RuntimeError):
    """Raised when an entry's `before` is missing — we refuse to guess."""


def invert_iam_update_assume_role_policy(entry: JournalEntry, *, iam: IamClient) -> None:
    if not entry.role_arn:
        raise CorruptedJournalError(f"journal entry for {entry.op.value} missing role_arn")
    before = entry.before
    if not before:
        raise CorruptedJournalError(
            f"journal entry for {entry.op.value} on {entry.role_arn} has no `before` policy"
        )
    iam.update_assume_role_policy(role_name_from_arn(entry.role_arn), before)


def invert_create_pod_identity_association(entry: JournalEntry, *, eks: EksClient) -> None:
    after = entry.after or {}
    assoc_id = after.get("associationId")
    if not assoc_id or not entry.cluster:
        raise CorruptedJournalError(
            f"journal entry for {entry.op.value} missing associationId/cluster"
        )
    eks.delete_pod_identity_association(entry.cluster, str(assoc_id))


def invert_remove_sa_annotation(entry: JournalEntry, *, k8s: K8sClient) -> None:
    before = entry.before or {}
    key = before.get("key")
    value = before.get("value")
    if not key:
        raise CorruptedJournalError(
            f"journal entry for {entry.op.value} on {entry.sa} has no annotation key"
        )
    if value is None:
        raise CorruptedJournalError(
            f"journal entry for {entry.op.value} on {entry.sa} has no prior value"
        )
    k8s.patch_service_account_annotations(entry.sa.namespace, entry.sa.name, {str(key): str(value)})


# Dispatcher
INVERSES: dict[JournalOp, str] = {
    JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY: "iam",
    JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION: "eks",
    JournalOp.K8S_REMOVE_SA_ANNOTATION: "k8s",
}
