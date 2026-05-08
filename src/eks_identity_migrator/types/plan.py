"""Plan data model — what `plan` produces and `apply` consumes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from eks_identity_migrator.types._base import CamelModel
from eks_identity_migrator.types.inventory import (
    ClusterRef,
    FindingModel,
    RiskClassification,
    SARef,
)

Strategy = Literal["append", "replace"]


class AssociationSpec(CamelModel):
    cluster_name: str
    namespace: str
    service_account: str
    role_arn: str


class AnnotationCleanup(CamelModel):
    namespace: str
    service_account: str
    annotation_key: str = "eks.amazonaws.com/role-arn"


class PlanStep(CamelModel):
    sa: SARef
    role_arn: str
    risk: RiskClassification
    skip: bool = False
    skip_reason: str | None = None

    trust_policy_before: dict[str, Any] = Field(default_factory=dict)
    trust_policy_after: dict[str, Any] = Field(default_factory=dict)

    association_create: AssociationSpec
    annotation_cleanup: AnnotationCleanup | None = None

    findings: list[FindingModel] = Field(default_factory=list)


class Plan(CamelModel):
    cluster: ClusterRef
    strategy: Strategy
    generated_at: datetime
    steps: list[PlanStep] = Field(default_factory=list)
