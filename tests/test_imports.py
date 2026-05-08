"""Boundary rule: only modules under aws/ and k8s/ may import boto3 / kubernetes.

The rule keeps every other module pure-Python and Protocol-injected so the
audit, plan, apply, verify, rollback, policy, risk, and types layers can be
unit-tested without spinning up clients.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1] / "src" / "eks_identity_migrator"
ALLOWED_BOUNDARY = {"aws", "k8s"}
FORBIDDEN_TOP = {"boto3", "botocore", "kubernetes"}


def _module_segments(path: Path) -> tuple[str, ...]:
    rel = path.relative_to(PKG_ROOT)
    return tuple(rel.parts)


def _imported_top_levels(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".", 1)[0])
    return out


def test_no_forbidden_imports_outside_boundary_modules() -> None:
    offenders: list[tuple[str, set[str]]] = []
    for py in PKG_ROOT.rglob("*.py"):
        segments = _module_segments(py)
        # Skip files inside aws/ and k8s/
        if segments and segments[0] in ALLOWED_BOUNDARY:
            continue
        tree = ast.parse(py.read_text())
        forbidden = _imported_top_levels(tree) & FORBIDDEN_TOP
        if forbidden:
            offenders.append((str(py.relative_to(PKG_ROOT)), forbidden))
    assert not offenders, (
        "Boundary violation — these modules import boto3/botocore/kubernetes "
        f"but are not under aws/ or k8s/: {offenders}"
    )
