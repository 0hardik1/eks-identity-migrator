"""NDJSON journal reader — tolerant of partial last line."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from eks_identity_migrator.types.journal import JournalEntry


def read_journal(path: str | Path) -> list[JournalEntry]:
    """Return every well-formed entry in `path` in file order."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[JournalEntry] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = JournalEntry.model_validate_json(line)
        except Exception:
            # Tolerate a corrupt last line (crash mid-write).
            continue
        out.append(entry)
    return out


def iter_journal_reverse(path: str | Path) -> Iterator[JournalEntry]:
    """Iterate entries in reverse order — used by rollback."""
    yield from reversed(read_journal(path))
