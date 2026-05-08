"""Inventory data model — what `audit` produces."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from eks_identity_migrator.types._base import CamelModel


class RiskClassification(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GRAY = "gray"


Severity = Literal["info", "warn", "error"]


class FindingModel(CamelModel):
    """A single classifier finding attached to a Mapping.

    `code` is loosely typed as `str` here (rather than the StrEnum from
    `risk.codes`) to keep this module dependency-free; the classifier always
    uses the StrEnum and serializes to its string value.
    """

    code: str
    severity: Severity
    message: str
    hint: str | None = None


class ClusterRef(CamelModel):
    name: str
    region: str
    account: str
    oidc_issuer: str
    arn: str


class SARef(CamelModel):
    namespace: str
    name: str

    def __str__(self) -> str:
        return f"{self.namespace}/{self.name}"


class PodRef(CamelModel):
    namespace: str
    name: str
    owner: str = ""


class Mapping(CamelModel):
    sa: SARef
    role_arn: str
    trust_policy: dict[str, Any]
    permission_boundary: str | None = None
    used_by_pods: list[PodRef] = Field(default_factory=list)
    risk: RiskClassification = RiskClassification.GRAY
    findings: list[FindingModel] = Field(default_factory=list)


class Inventory(CamelModel):
    cluster: ClusterRef
    generated_at: datetime
    mappings: list[Mapping] = Field(default_factory=list)
    orphan_roles: list[str] = Field(default_factory=list)
    stale_annotations: list[SARef] = Field(default_factory=list)
