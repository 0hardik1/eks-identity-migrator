"""Trust-policy parser tests using fixtures under testdata/trust-policies/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eks_identity_migrator.policy.parser import (
    TrustPolicyParseError,
    parse_trust_policy,
    try_parse_trust_policy,
)

FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "trust-policies"


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_parse_minimum_green() -> None:
    policy = load("00a_green_minimum.in.json")
    parsed = parse_trust_policy(policy)
    assert parsed.version == "2012-10-17"
    assert len(parsed.statements) == 1
    s = parsed.statements[0]
    assert s.effect == "Allow"
    assert s.actions == ("sts:AssumeRoleWithWebIdentity",)
    assert len(s.principal_federated) == 1
    assert "oidc-provider/" in s.principal_federated[0]
    aud = s.condition_value("StringEquals", "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:aud")
    assert aud == ("sts.amazonaws.com",)


def test_parse_with_sid_preserved() -> None:
    parsed = parse_trust_policy(load("00b_green_with_sid.in.json"))
    assert parsed.statements[0].sid == "AllowFromCluster"


def test_parse_principal_federated_as_array() -> None:
    parsed = parse_trust_policy(load("00f_principal_federated_array.in.json"))
    assert len(parsed.statements[0].principal_federated) == 1


def test_parse_multi_statement_multi_cluster() -> None:
    parsed = parse_trust_policy(load("01_multi_cluster_role_reuse.in.json"))
    assert len(parsed.statements) == 2
    issuers = parsed.federated_oidc_issuers()
    assert any("CLUSTERA" in i for i in issuers)
    assert any("CLUSTERB" in i for i in issuers)


def test_parse_wildcard_sub_via_stringlike() -> None:
    parsed = parse_trust_policy(load("03_wildcard_sub.in.json"))
    sub = parsed.statements[0].condition_value(
        "StringLike", "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub"
    )
    assert sub is not None
    assert sub[0].endswith("*")


def test_parse_forall_multi_sub() -> None:
    parsed = parse_trust_policy(load("04_forall_multi_sub.in.json"))
    sub = parsed.statements[0].condition_value(
        "ForAllValues:StringEquals",
        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub",
    )
    assert sub is not None
    assert len(sub) == 2


def test_parse_action_as_list() -> None:
    parsed = parse_trust_policy(load("15_tagsession_already_present.in.json"))
    actions = parsed.statements[0].actions
    assert "sts:AssumeRoleWithWebIdentity" in actions
    assert "sts:TagSession" in actions


def test_parse_mixed_ec2_irsa_principals() -> None:
    parsed = parse_trust_policy(load("14_mixed_ec2_irsa.in.json"))
    assert parsed.has_service_principal("ec2.amazonaws.com")
    assert any(s.principal_federated for s in parsed.statements)


def test_parse_invalid_statement_type_raises() -> None:
    bad = load("00d_policy_parse_error.in.json")
    with pytest.raises(TrustPolicyParseError):
        parse_trust_policy(bad)


def test_try_parse_returns_none_on_error() -> None:
    assert try_parse_trust_policy({"Version": "2012-10-17"}) is None
    assert try_parse_trust_policy("not json {") is None


def test_parse_string_input() -> None:
    raw = json.dumps(load("00a_green_minimum.in.json"))
    parsed = parse_trust_policy(raw)
    assert parsed.version == "2012-10-17"


def test_parse_principal_wildcard_string() -> None:
    parsed = parse_trust_policy(
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "sts:AssumeRole"}],
        }
    )
    assert parsed.statements[0].principal_aws == ("*",)


def test_parse_single_statement_object() -> None:
    """Statement may be a single object rather than a list."""
    parsed = parse_trust_policy(
        {
            "Version": "2012-10-17",
            "Statement": {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            },
        }
    )
    assert len(parsed.statements) == 1
    assert parsed.statements[0].principal_service == ("ec2.amazonaws.com",)
