"""Append-only NDJSON journal — first-class artifact (spec §15)."""

from eks_identity_migrator.journal.reader import iter_journal_reverse, read_journal
from eks_identity_migrator.journal.writer import JournalWriter, default_journal_path

__all__ = [
    "JournalWriter",
    "default_journal_path",
    "iter_journal_reverse",
    "read_journal",
]
