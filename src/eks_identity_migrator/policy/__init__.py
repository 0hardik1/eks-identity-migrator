"""JSON-semantic trust-policy operations: parse, canonicalize, translate, diff."""

from eks_identity_migrator.policy.canonicalizer import (
    canonical_json,
    canonicalize,
    policies_equivalent,
)
from eks_identity_migrator.policy.differ import unified_diff
from eks_identity_migrator.policy.parser import (
    ParsedPolicy,
    Statement,
    TrustPolicyParseError,
    parse_trust_policy,
    try_parse_trust_policy,
)
from eks_identity_migrator.policy.translator import (
    POD_IDENTITY_SERVICE,
    build_pod_identity_statement,
    translate,
    translate_canonical_json,
)

__all__ = [
    "POD_IDENTITY_SERVICE",
    "ParsedPolicy",
    "Statement",
    "TrustPolicyParseError",
    "build_pod_identity_statement",
    "canonical_json",
    "canonicalize",
    "parse_trust_policy",
    "policies_equivalent",
    "translate",
    "translate_canonical_json",
    "try_parse_trust_policy",
    "unified_diff",
]
