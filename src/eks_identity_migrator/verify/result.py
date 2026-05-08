"""VerifyResult — per-SA verification state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from eks_identity_migrator.types.inventory import SARef


class VerifyStatus(StrEnum):
    POD_IDENTITY = "pod-identity"
    IRSA = "irsa"
    DUAL = "dual"
    DEFERRED = "deferred"
    FAILED = "failed"


@dataclass
class VerifyEntry:
    sa: SARef
    status: VerifyStatus
    pod: str | None = None
    note: str | None = None
    probe_arn: str | None = None


@dataclass
class VerifyResult:
    entries: list[VerifyEntry] = field(default_factory=list)

    def add(self, entry: VerifyEntry) -> None:
        self.entries.append(entry)

    def has_failures(self) -> bool:
        return any(e.status == VerifyStatus.FAILED for e in self.entries)

    def has_remaining_irsa(self) -> bool:
        return any(e.status == VerifyStatus.IRSA for e in self.entries)
