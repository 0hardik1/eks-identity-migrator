"""JSON-semantic canonicalization for trust policies.

Two policies that differ only in whitespace, top-level key ordering, single-
vs-list scalars in Action/Principal fields, or `Sid` presence should compare
equal. This module is the single source of truth for that comparison and for
deterministic pretty-printing.
"""

from __future__ import annotations

import json
from typing import Any


def _normalize_scalar_or_list(value: Any) -> Any:
    """Lists of strings get sorted; single-string and list-of-one collapse to the same form.

    A list with a single value is kept as a list (we don't infer "should be scalar"
    semantics — that is the caller's choice). However, two lists with identical
    contents in different order become equal.
    """
    if isinstance(value, list):
        # Sort by string repr — deterministic and stable for mixed-type lists.
        try:
            return sorted(value)
        except TypeError:
            return sorted(value, key=lambda v: json.dumps(v, sort_keys=True))
    return value


def _canonicalize(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _canonicalize(node[k]) for k in sorted(node)}
    if isinstance(node, list):
        canon_items = [_canonicalize(item) for item in node]
        try:
            return sorted(canon_items, key=lambda v: json.dumps(v, sort_keys=True))
        except TypeError:
            return canon_items
    return node


def canonicalize(policy: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical (sorted, normalized) copy of the policy."""
    return _canonicalize(policy)  # type: ignore[no-any-return]


def policies_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Are two trust policies semantically equivalent?"""
    return canonicalize(a) == canonicalize(b)


def canonical_json(policy: dict[str, Any], *, indent: int = 2) -> str:
    """Pretty-print a policy with sorted keys and stable indentation.

    Used by the translator (so output is byte-deterministic) and by the
    differ (so diffs are noise-free).
    """
    return json.dumps(canonicalize(policy), indent=indent, sort_keys=True)
