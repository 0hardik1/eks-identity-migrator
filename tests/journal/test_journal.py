"""Journal writer + reader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from eks_identity_migrator.journal import (
    JournalWriter,
    iter_journal_reverse,
    read_journal,
)
from eks_identity_migrator.journal.writer import default_journal_path
from eks_identity_migrator.types import JournalOp, JournalStatus, SARef


def test_writer_creates_parent_dir(tmp_path: Path) -> None:
    j = tmp_path / "nested" / "journal.jsonl"
    JournalWriter(j)
    assert j.parent.exists()


def test_write_and_read_one_entry(tmp_path: Path) -> None:
    w = JournalWriter(tmp_path / "j.jsonl")
    w.write(
        JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
        JournalStatus.SUCCESS,
        SARef(namespace="prod", name="app"),
        role_arn="arn:aws:iam::123:role/app",
        before={"policy": {"x": 1}},
        after={"policy": {"x": 2}},
    )
    entries = read_journal(tmp_path / "j.jsonl")
    assert len(entries) == 1
    e = entries[0]
    assert e.op == JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY
    assert e.status == JournalStatus.SUCCESS
    assert e.sa.name == "app"
    assert e.before == {"policy": {"x": 1}}


def test_pending_then_success_flow(tmp_path: Path) -> None:
    w = JournalWriter(tmp_path / "j.jsonl")
    sa = SARef(namespace="prod", name="app")
    w.write(JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY, JournalStatus.PENDING, sa)
    w.write(JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY, JournalStatus.SUCCESS, sa)
    entries = read_journal(tmp_path / "j.jsonl")
    assert [e.status for e in entries] == [JournalStatus.PENDING, JournalStatus.SUCCESS]


def test_reverse_iteration(tmp_path: Path) -> None:
    w = JournalWriter(tmp_path / "j.jsonl")
    sa = SARef(namespace="ns", name="x")
    for op in (
        JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
        JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION,
        JournalOp.K8S_REMOVE_SA_ANNOTATION,
    ):
        w.write(op, JournalStatus.SUCCESS, sa)
    rev = list(iter_journal_reverse(tmp_path / "j.jsonl"))
    assert [e.op for e in rev] == [
        JournalOp.K8S_REMOVE_SA_ANNOTATION,
        JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION,
        JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
    ]


def test_corrupt_last_line_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    w = JournalWriter(p)
    w.write(
        JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
        JournalStatus.SUCCESS,
        SARef(namespace="ns", name="x"),
    )
    with p.open("a") as f:
        f.write('{"ts": "garbage')  # truncated
    entries = read_journal(p)
    assert len(entries) == 1


def test_default_journal_path_under_dot_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    p = default_journal_path()
    assert ".eks-identity-migrator" in str(p)
    assert p.name.startswith("journal-")


def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_journal(tmp_path / "nope.jsonl") == []
