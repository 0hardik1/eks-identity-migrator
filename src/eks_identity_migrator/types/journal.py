"""Journal data model — append-only NDJSON record of every apply operation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from eks_identity_migrator.types._base import CamelModel
from eks_identity_migrator.types.inventory import SARef


class JournalOp(StrEnum):
    """Operations recorded in the journal. Names mirror the IAM/EKS/K8s actions."""

    IAM_UPDATE_ASSUME_ROLE_POLICY = "iam:UpdateAssumeRolePolicy"
    EKS_CREATE_POD_IDENTITY_ASSOCIATION = "eks:CreatePodIdentityAssociation"
    EKS_DELETE_POD_IDENTITY_ASSOCIATION = "eks:DeletePodIdentityAssociation"
    K8S_REMOVE_SA_ANNOTATION = "k8s:RemoveSAAnnotation"
    K8S_RESTORE_SA_ANNOTATION = "k8s:RestoreSAAnnotation"


class JournalStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


class JournalEntry(CamelModel):
    """One line in the NDJSON journal.

    `before` and `after` capture the JSON-semantic state surrounding the op
    (the trust policy, the association id, the annotation value) so rollback
    can compute the inverse without re-reading remote state.
    """

    ts: datetime
    op: JournalOp
    status: JournalStatus
    sa: SARef
    role_arn: str | None = None
    cluster: str | None = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    note: str | None = None
