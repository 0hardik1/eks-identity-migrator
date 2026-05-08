"""Append-only NDJSON journal writer (spec §9 + §15).

Every apply operation writes `pending` first, then either `success` or
`failure`. The file is fsynced after each line so a crash leaves a recoverable
journal for rollback.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from eks_identity_migrator.types.inventory import SARef
from eks_identity_migrator.types.journal import JournalEntry, JournalOp, JournalStatus


class JournalWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_entry(self, entry: JournalEntry) -> None:
        line = entry.model_dump_json(by_alias=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def write(
        self,
        op: JournalOp,
        status: JournalStatus,
        sa: SARef,
        *,
        role_arn: str | None = None,
        cluster: str | None = None,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
        error: str | None = None,
        note: str | None = None,
    ) -> JournalEntry:
        entry = JournalEntry(
            ts=datetime.now(UTC),
            op=op,
            status=status,
            sa=sa,
            role_arn=role_arn,
            cluster=cluster,
            before=before or {},
            after=after or {},
            error=error,
            note=note,
        )
        self.write_entry(entry)
        return entry


def default_journal_path(*, base_dir: str | Path = ".eks-identity-migrator") -> Path:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return base / f"journal-{ts}.json"
