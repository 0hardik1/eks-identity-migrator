"""Trust-policy translator.

Converts an IRSA trust policy into one that grants Pod Identity, per the
spec §7.3 strategies:

- **append**: add a Pod Identity statement next to existing OIDC statements
  (preserving cross-cluster trust). Idempotent: if an equivalent Pod Identity
  statement is already present, it is not duplicated.
- **replace**: strip OIDC-only statements but preserve non-OIDC principals
  (e.g., EC2 service principal — gotcha 14), then append the Pod Identity
  statement.

The Pod Identity statement always emits both `aws:SourceAccount` (StringEquals)
and `aws:SourceArn` (ArnEquals) for confused-deputy prevention (spec §7.3 hard
requirement).
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from eks_identity_migrator.policy.canonicalizer import canonical_json, canonicalize
from eks_identity_migrator.policy.parser import parse_trust_policy

Strategy = Literal["append", "replace"]

POD_IDENTITY_SERVICE = "pods.eks.amazonaws.com"
POD_IDENTITY_ACTIONS = ("sts:AssumeRole", "sts:TagSession")


def build_pod_identity_statement(
    *,
    cluster_arn: str,
    account: str,
    sa_name: str,
    sid: str | None = None,
) -> dict[str, Any]:
    """Construct the canonical Pod Identity statement for a given SA."""
    statement: dict[str, Any] = {
        "Effect": "Allow",
        "Principal": {"Service": POD_IDENTITY_SERVICE},
        "Action": list(POD_IDENTITY_ACTIONS),
        "Condition": {
            "StringEquals": {"aws:SourceAccount": account},
            "ArnEquals": {"aws:SourceArn": cluster_arn},
        },
    }
    if sid is not None:
        statement["Sid"] = sid
    elif sa_name:
        # Generate a stable Sid derived from the SA name (alnum-only).
        slug = "".join(c for c in sa_name if c.isalnum())
        if slug:
            statement["Sid"] = f"PodIdentityFor{slug[:32]}"
    return statement


def _is_pod_identity_statement(stmt: dict[str, Any]) -> bool:
    """True if this statement grants Pod Identity (regardless of conditions)."""
    principal = stmt.get("Principal", {})
    if not isinstance(principal, dict):
        return False
    service = principal.get("Service")
    if isinstance(service, str):
        return service == POD_IDENTITY_SERVICE
    if isinstance(service, list):
        return POD_IDENTITY_SERVICE in service
    return False


def _is_oidc_irsa_statement(stmt: dict[str, Any]) -> bool:
    """True if this statement is the IRSA pattern (Federated + AssumeRoleWithWebIdentity)."""
    principal = stmt.get("Principal", {})
    if not isinstance(principal, dict) or "Federated" not in principal:
        return False
    actions = stmt.get("Action", [])
    if isinstance(actions, str):
        actions = [actions]
    return "sts:AssumeRoleWithWebIdentity" in actions


def translate(
    policy: dict[str, Any],
    *,
    strategy: Strategy,
    cluster_arn: str,
    account: str,
    sa_name: str,
) -> dict[str, Any]:
    """Translate a trust policy. Returns a NEW dict; input is not mutated.

    Idempotency: if append produces a policy equivalent to the input, the
    input is returned unchanged (modulo a deep copy).
    """
    parse_trust_policy(policy)  # validate; raises on malformed input

    new_stmt = build_pod_identity_statement(
        cluster_arn=cluster_arn,
        account=account,
        sa_name=sa_name,
    )

    out: dict[str, Any] = copy.deepcopy(policy)
    raw_stmts = out.get("Statement")
    if isinstance(raw_stmts, dict):
        existing = [raw_stmts]
    elif isinstance(raw_stmts, list):
        existing = list(raw_stmts)
    else:
        existing = []

    if strategy == "replace":
        # Drop pure-OIDC IRSA statements, keep everything else (e.g., EC2 service principals).
        kept = [s for s in existing if isinstance(s, dict) and not _is_oidc_irsa_statement(s)]
    else:
        kept = list(existing)

    # De-duplicate: if an equivalent Pod Identity statement already exists, skip adding.
    new_canon = canonicalize(new_stmt)
    already_present = any(
        isinstance(s, dict) and _is_pod_identity_statement(s) and canonicalize(s) == new_canon
        for s in kept
    )
    if not already_present:
        kept.append(new_stmt)

    out["Statement"] = kept
    if "Version" not in out:
        out["Version"] = "2012-10-17"
    return out


def translate_canonical_json(
    policy: dict[str, Any],
    *,
    strategy: Strategy,
    cluster_arn: str,
    account: str,
    sa_name: str,
) -> str:
    """Translate and return canonical-JSON pretty-printed output."""
    return canonical_json(
        translate(
            policy,
            strategy=strategy,
            cluster_arn=cluster_arn,
            account=account,
            sa_name=sa_name,
        )
    )
