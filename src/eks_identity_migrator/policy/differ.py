"""Human-readable diff between two trust policies (canonicalized)."""

from __future__ import annotations

import difflib
from typing import Any

from eks_identity_migrator.policy.canonicalizer import canonical_json


def unified_diff(before: dict[str, Any], after: dict[str, Any], *, context: int = 3) -> str:
    """Return a unified diff of canonical pretty-prints. Empty string if equal."""
    lhs = canonical_json(before).splitlines(keepends=True)
    rhs = canonical_json(after).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            lhs,
            rhs,
            fromfile="before",
            tofile="after",
            n=context,
        )
    )
