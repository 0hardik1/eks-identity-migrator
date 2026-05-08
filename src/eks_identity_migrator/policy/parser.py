"""Trust-policy parser.

Normalizes the polymorphism in IAM policy JSON:

- `Statement` may be a single object or a list of objects.
- `Principal` may be `{"Federated": "..."}` or `{"Federated": [...]}` (also for `AWS`, `Service`).
- `Condition` keys are operators (`StringEquals`, `StringLike`,
  `ForAllValues:StringEquals`, `ArnEquals`, ...) whose values map keys to
  string-or-list-of-strings.
- `Action` may be a single string or a list.

The parser does NOT classify; it only reshapes the policy into a structure
the classifier rules can query without reimplementing the polymorphism.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class TrustPolicyParseError(ValueError):
    """Raised when a trust policy cannot be parsed."""


@dataclass(frozen=True)
class Statement:
    sid: str | None
    effect: str
    actions: tuple[str, ...]
    principal_federated: tuple[str, ...]
    principal_aws: tuple[str, ...]
    principal_service: tuple[str, ...]
    # condition_operator -> {key -> tuple of values}
    conditions: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)

    def has_principal_federated_with(self, predicate: Any) -> bool:
        return any(predicate(p) for p in self.principal_federated)

    def condition_value(self, operator: str, key: str) -> tuple[str, ...] | None:
        return self.conditions.get(operator, {}).get(key)


@dataclass(frozen=True)
class ParsedPolicy:
    version: str
    statements: tuple[Statement, ...]

    @property
    def federated_principals(self) -> tuple[str, ...]:
        out: list[str] = []
        for s in self.statements:
            out.extend(s.principal_federated)
        return tuple(out)

    @property
    def all_actions(self) -> tuple[str, ...]:
        out: list[str] = []
        for s in self.statements:
            out.extend(s.actions)
        return tuple(out)

    def has_service_principal(self, service: str) -> bool:
        return any(service in s.principal_service for s in self.statements)

    def has_principal_aws(self) -> bool:
        return any(s.principal_aws for s in self.statements)

    def federated_oidc_issuers(self) -> tuple[str, ...]:
        """OIDC issuer host paths derived from federated principals.

        Example: `arn:aws:iam::111:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/EX`
        → `oidc.eks.us-west-2.amazonaws.com/id/EX`.
        """
        issuers: list[str] = []
        for fed in self.federated_principals:
            if ":oidc-provider/" in fed:
                issuers.append(fed.split(":oidc-provider/", 1)[1])
        return tuple(issuers)


def _to_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    raise TrustPolicyParseError(f"expected string or list, got {type(value).__name__}")


def _parse_principal(principal: Any) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (federated, aws, service)."""
    if principal is None:
        return ((), (), ())
    if isinstance(principal, str):
        # `Principal: "*"` form — treat as a wildcard AWS principal.
        return ((), (principal,), ())
    if not isinstance(principal, dict):
        raise TrustPolicyParseError(f"Principal must be string or object, got {type(principal)}")
    return (
        _to_tuple(principal.get("Federated")),
        _to_tuple(principal.get("AWS")),
        _to_tuple(principal.get("Service")),
    )


def _parse_conditions(condition: Any) -> dict[str, dict[str, tuple[str, ...]]]:
    if condition is None:
        return {}
    if not isinstance(condition, dict):
        raise TrustPolicyParseError("Condition must be an object")
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for op, key_map in condition.items():
        if not isinstance(key_map, dict):
            raise TrustPolicyParseError(f"Condition.{op} must be an object")
        out[op] = {k: _to_tuple(v) for k, v in key_map.items()}
    return out


def _parse_statement(raw: Any) -> Statement:
    if not isinstance(raw, dict):
        raise TrustPolicyParseError(f"Statement must be object, got {type(raw)}")
    federated, aws, service = _parse_principal(raw.get("Principal"))
    return Statement(
        sid=raw.get("Sid"),
        effect=str(raw.get("Effect", "")),
        actions=_to_tuple(raw.get("Action")),
        principal_federated=federated,
        principal_aws=aws,
        principal_service=service,
        conditions=_parse_conditions(raw.get("Condition")),
    )


def parse_trust_policy(policy: dict[str, Any] | str) -> ParsedPolicy:
    """Parse an IAM trust policy (dict or JSON string) into a `ParsedPolicy`.

    Raises TrustPolicyParseError on any structural issue.
    """
    if isinstance(policy, str):
        try:
            policy = json.loads(policy)
        except json.JSONDecodeError as exc:
            raise TrustPolicyParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(policy, dict):
        raise TrustPolicyParseError("trust policy must be an object")
    raw_stmts = policy.get("Statement")
    if raw_stmts is None:
        raise TrustPolicyParseError("missing Statement")
    if isinstance(raw_stmts, dict):
        raw_stmts = [raw_stmts]
    if not isinstance(raw_stmts, list):
        raise TrustPolicyParseError("Statement must be object or array")
    statements = tuple(_parse_statement(s) for s in raw_stmts)
    return ParsedPolicy(
        version=str(policy.get("Version", "")),
        statements=statements,
    )


def try_parse_trust_policy(policy: dict[str, Any] | str) -> ParsedPolicy | None:
    """Parse, returning None on failure (for the `gray` finding path)."""
    try:
        return parse_trust_policy(policy)
    except TrustPolicyParseError:
        return None
