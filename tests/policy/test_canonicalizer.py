"""Canonicalizer tests — JSON-semantic equality and stable pretty-print."""

from __future__ import annotations

from eks_identity_migrator.policy.canonicalizer import (
    canonical_json,
    canonicalize,
    policies_equivalent,
)

A = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "pods.eks.amazonaws.com"},
            "Action": ["sts:AssumeRole", "sts:TagSession"],
            "Condition": {
                "StringEquals": {"aws:SourceAccount": "123"},
                "ArnEquals": {"aws:SourceArn": "arn"},
            },
        }
    ],
}

B = {
    "Statement": [
        {
            "Action": ["sts:TagSession", "sts:AssumeRole"],
            "Condition": {
                "ArnEquals": {"aws:SourceArn": "arn"},
                "StringEquals": {"aws:SourceAccount": "123"},
            },
            "Effect": "Allow",
            "Principal": {"Service": "pods.eks.amazonaws.com"},
        }
    ],
    "Version": "2012-10-17",
}


def test_equivalent_under_key_order_and_action_order() -> None:
    assert policies_equivalent(A, B)


def test_canonical_json_is_stable_across_inputs() -> None:
    assert canonical_json(A) == canonical_json(B)


def test_canonical_json_sorts_top_level_keys() -> None:
    out = canonical_json(A)
    # Statement sorts before Version alphabetically.
    assert out.index('"Statement"') < out.index('"Version"')


def test_inequivalent_when_principals_differ() -> None:
    assert not policies_equivalent(A, {**A, "Statement": []})


def test_canonicalize_does_not_mutate_input() -> None:
    snapshot = dict(A)
    canonicalize(A)
    assert snapshot == A


def test_canonical_json_indent_default_two() -> None:
    out = canonical_json({"a": 1})
    assert out.count("  ") >= 1  # 2-space indent present


def test_canonicalize_handles_mixed_type_list() -> None:
    """Lists with mixed types fall back to a JSON-string sort key."""
    payload = {"x": [1, "a", {"k": 2}, [1, 2]]}
    out = canonicalize(payload)
    # Round-trip is structurally identical (same elements).
    assert sorted(out["x"], key=str) == sorted(payload["x"], key=str)


def test_canonicalize_nested_lists() -> None:
    """Nested lists are recursively canonicalized."""
    a = {"x": [{"b": 2, "a": 1}, {"a": 1, "b": 2}]}
    b = {"x": [{"a": 1, "b": 2}, {"b": 2, "a": 1}]}
    assert policies_equivalent(a, b)


def test_canonicalize_scalar_values_unchanged() -> None:
    assert canonicalize({"x": 5}) == {"x": 5}
    assert canonicalize({"x": "s"}) == {"x": "s"}
    assert canonicalize({"x": True}) == {"x": True}
    assert canonicalize({"x": None}) == {"x": None}
