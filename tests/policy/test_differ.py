"""Tests for the human-readable differ used in dry-run output."""

from __future__ import annotations

from eks_identity_migrator.policy.differ import unified_diff


def test_diff_empty_when_equal() -> None:
    a = {"Version": "2012-10-17", "Statement": []}
    assert unified_diff(a, a) == ""


def test_diff_shows_added_statement() -> None:
    a = {"Version": "2012-10-17", "Statement": []}
    b = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*"}]}
    diff = unified_diff(a, b)
    assert "Effect" in diff
    assert "Allow" in diff
    assert "+" in diff
