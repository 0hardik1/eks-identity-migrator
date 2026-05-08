"""Translator tests — append/replace and idempotency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eks_identity_migrator.policy.canonicalizer import canonical_json, policies_equivalent
from eks_identity_migrator.policy.translator import (
    POD_IDENTITY_SERVICE,
    build_pod_identity_statement,
    translate,
    translate_canonical_json,
)

FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "translator"
CLUSTER_ARN = "arn:aws:eks:us-west-2:123456789012:cluster/my-cluster"
ACCOUNT = "123456789012"


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


# ---- build_pod_identity_statement ------------------------------------------


def test_built_statement_includes_mandatory_conditions() -> None:
    stmt = build_pod_identity_statement(
        cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="frontend"
    )
    assert stmt["Principal"]["Service"] == POD_IDENTITY_SERVICE  # type: ignore[index]
    assert "sts:AssumeRole" in stmt["Action"]
    assert "sts:TagSession" in stmt["Action"]
    assert stmt["Condition"]["StringEquals"]["aws:SourceAccount"] == ACCOUNT  # type: ignore[index]
    assert stmt["Condition"]["ArnEquals"]["aws:SourceArn"] == CLUSTER_ARN  # type: ignore[index]


def test_built_statement_generates_sid_from_sa_name() -> None:
    stmt = build_pod_identity_statement(
        cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    assert stmt["Sid"] == "PodIdentityForappfrontend"


def test_built_statement_explicit_sid_wins() -> None:
    stmt = build_pod_identity_statement(
        cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="ignored", sid="MySid"
    )
    assert stmt["Sid"] == "MySid"


# ---- append strategy -------------------------------------------------------


def test_append_t01_minimal_irsa() -> None:
    inp = load("t01_append_to_minimal_irsa.in.json")
    expected = load("t01_append_to_minimal_irsa.out.json")
    actual = translate(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    assert policies_equivalent(actual, expected)


def test_append_preserves_existing_pod_identity_statement_idempotent() -> None:
    inp = load("t01_append_to_minimal_irsa.in.json")
    once = translate(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    twice = translate(
        once, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    # Second translate should not duplicate the Pod Identity statement.
    assert policies_equivalent(once, twice)
    pi_count_once = sum(
        1
        for s in once["Statement"]
        if isinstance(s, dict) and s.get("Principal", {}).get("Service") == POD_IDENTITY_SERVICE
    )
    pi_count_twice = sum(
        1
        for s in twice["Statement"]
        if isinstance(s, dict) and s.get("Principal", {}).get("Service") == POD_IDENTITY_SERVICE
    )
    assert pi_count_once == pi_count_twice == 1


def test_append_preserves_existing_oidc_statements() -> None:
    inp = load("t01_append_to_minimal_irsa.in.json")
    out = translate(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    assert any(
        isinstance(s, dict)
        and isinstance(s.get("Principal"), dict)
        and "Federated" in s["Principal"]
        for s in out["Statement"]
    )


def test_append_preserves_ec2_principal() -> None:
    inp = load("t04_replace_strips_oidc_keeps_ec2.in.json")
    out = translate(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="tool"
    )
    services = [
        s["Principal"]["Service"]
        for s in out["Statement"]
        if isinstance(s, dict) and isinstance(s.get("Principal"), dict)
        and "Service" in s["Principal"]
    ]
    assert "ec2.amazonaws.com" in services
    assert POD_IDENTITY_SERVICE in services


# ---- replace strategy ------------------------------------------------------


def test_replace_strips_oidc_but_keeps_ec2() -> None:
    inp = load("t04_replace_strips_oidc_keeps_ec2.in.json")
    expected = load("t04_replace_strips_oidc_keeps_ec2.out.json")
    actual = translate(
        inp, strategy="replace", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="tool"
    )
    assert policies_equivalent(actual, expected)


def test_replace_drops_irsa_statements() -> None:
    inp = load("t01_append_to_minimal_irsa.in.json")
    out = translate(
        inp, strategy="replace", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    has_irsa = any(
        isinstance(s, dict)
        and isinstance(s.get("Principal"), dict)
        and "Federated" in s["Principal"]
        for s in out["Statement"]
    )
    assert not has_irsa


# ---- determinism + canonical output ---------------------------------------


def test_translate_does_not_mutate_input() -> None:
    inp = load("t01_append_to_minimal_irsa.in.json")
    snapshot = json.dumps(inp, sort_keys=True)
    translate(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    assert json.dumps(inp, sort_keys=True) == snapshot


def test_translate_canonical_json_byte_stable() -> None:
    inp = load("t01_append_to_minimal_irsa.in.json")
    a = translate_canonical_json(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    b = translate_canonical_json(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="app-frontend"
    )
    assert a == b
    # Sorted-key invariant: every line's first-occurring key is alphabetical
    # within its dict — easier to sanity-check with canonical_json directly.
    again = canonical_json(
        translate(
            inp,
            strategy="append",
            cluster_arn=CLUSTER_ARN,
            account=ACCOUNT,
            sa_name="app-frontend",
        )
    )
    assert a == again


def test_translate_invalid_policy_raises() -> None:
    with pytest.raises(Exception):
        translate(
            {"Version": "2012-10-17", "Statement": "bad"},
            strategy="append",
            cluster_arn=CLUSTER_ARN,
            account=ACCOUNT,
            sa_name="x",
        )


def test_translate_adds_version_when_missing() -> None:
    inp: dict[str, object] = {"Statement": []}
    out = translate(
        inp, strategy="append", cluster_arn=CLUSTER_ARN, account=ACCOUNT, sa_name="x"
    )
    assert out["Version"] == "2012-10-17"
