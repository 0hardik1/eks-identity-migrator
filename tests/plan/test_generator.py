"""Plan generator tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eks_identity_migrator.plan.generator import generate
from eks_identity_migrator.plan.io import read_plan, write_plan
from eks_identity_migrator.policy.canonicalizer import canonicalize
from eks_identity_migrator.policy.translator import POD_IDENTITY_SERVICE
from eks_identity_migrator.types.inventory import (
    ClusterRef,
    FindingModel,
    Inventory,
    Mapping,
    PodRef,
    RiskClassification,
    SARef,
)

FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "trust-policies"
CLUSTER = ClusterRef(
    name="my-cluster",
    region="us-west-2",
    account="123456789012",
    oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
    arn="arn:aws:eks:us-west-2:123456789012:cluster/my-cluster",
)


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def make_inventory(*mappings: Mapping) -> Inventory:
    return Inventory(
        cluster=CLUSTER,
        generated_at=datetime(2026, 5, 8, 14, 32, tzinfo=UTC),
        mappings=list(mappings),
    )


def green_mapping() -> Mapping:
    return Mapping(
        sa=SARef(namespace="prod", name="app"),
        role_arn="arn:aws:iam::123456789012:role/app",
        trust_policy=load("00a_green_minimum.in.json"),
        used_by_pods=[PodRef(namespace="prod", name="app-1", owner="Deployment/app")],
        risk=RiskClassification.GREEN,
    )


def red_mapping() -> Mapping:
    return Mapping(
        sa=SARef(namespace="data", name="etl"),
        role_arn="arn:aws:iam::222222222222:role/etl",
        trust_policy=load("02_cross_account_trust.in.json"),
        used_by_pods=[PodRef(namespace="data", name="etl-1", owner="Job/etl")],
        risk=RiskClassification.RED,
        findings=[FindingModel(code="CROSS_ACCOUNT_TRUST", severity="error", message="x")],
    )


def yellow_mapping() -> Mapping:
    return Mapping(
        sa=SARef(namespace="kube-system", name="aws-load-balancer-controller"),
        role_arn="arn:aws:iam::123456789012:role/alb",
        trust_policy=load("09a_operator_alb.in.json"),
        used_by_pods=[PodRef(namespace="kube-system", name="alb-1", owner="Deployment/alb")],
        risk=RiskClassification.YELLOW,
        findings=[FindingModel(code="OPERATOR_MANAGED", severity="warn", message="y")],
    )


def test_generate_emits_step_per_mapping() -> None:
    inv = make_inventory(green_mapping(), red_mapping())
    plan = generate(inv)
    assert len(plan.steps) == 2


def test_generate_red_is_skipped_with_reason() -> None:
    inv = make_inventory(red_mapping())
    plan = generate(inv)
    assert plan.steps[0].skip
    assert plan.steps[0].skip_reason == "CROSS_ACCOUNT_TRUST"


def test_generate_yellow_skipped_unless_include_yellow() -> None:
    inv = make_inventory(yellow_mapping())
    plan = generate(inv, include_yellow=False)
    assert plan.steps[0].skip
    plan2 = generate(inv, include_yellow=True)
    assert not plan2.steps[0].skip


def test_generate_green_step_has_translated_after_with_pod_identity() -> None:
    inv = make_inventory(green_mapping())
    plan = generate(inv)
    after = plan.steps[0].trust_policy_after
    services = [
        s["Principal"]["Service"]
        for s in after["Statement"]
        if isinstance(s, dict)
        and isinstance(s.get("Principal"), dict)
        and "Service" in s["Principal"]
    ]
    assert POD_IDENTITY_SERVICE in services


def test_replace_strategy_promotes_multi_cluster_to_red() -> None:
    multi = Mapping(
        sa=SARef(namespace="prod", name="app"),
        role_arn="arn:aws:iam::123456789012:role/app",
        trust_policy=load("01_multi_cluster_role_reuse.in.json"),
        used_by_pods=[PodRef(namespace="prod", name="app-1", owner="Deployment/app")],
        risk=RiskClassification.YELLOW,
        findings=[
            FindingModel(
                code="ROLE_USED_BY_MULTIPLE_CLUSTERS",
                severity="warn",
                message="multi-cluster",
            )
        ],
    )
    plan = generate(make_inventory(multi), strategy="replace")
    assert plan.steps[0].risk == RiskClassification.RED
    assert plan.steps[0].skip
    assert plan.steps[0].skip_reason == "ROLE_USED_BY_MULTIPLE_CLUSTERS"


def test_plan_yaml_round_trip(tmp_path: Path) -> None:
    inv = make_inventory(green_mapping(), red_mapping())
    plan = generate(inv)
    out = tmp_path / "plan.yaml"
    write_plan(plan, out)
    plan2 = read_plan(out)
    # Trust policies are equivalent (canonicalized) — datetime tz preserved
    for step1, step2 in zip(plan.steps, plan2.steps, strict=True):
        assert step1.sa == step2.sa
        assert step1.role_arn == step2.role_arn
        assert step1.skip == step2.skip
        assert canonicalize(step1.trust_policy_before) == canonicalize(step2.trust_policy_before)
        assert canonicalize(step1.trust_policy_after) == canonicalize(step2.trust_policy_after)


def test_plan_yaml_byte_stable(tmp_path: Path) -> None:
    plan = generate(make_inventory(green_mapping()))
    p1 = tmp_path / "p1.yaml"
    p2 = tmp_path / "p2.yaml"
    write_plan(plan, p1)
    write_plan(plan, p2)
    assert p1.read_text() == p2.read_text()


def test_invalid_strategy_raises() -> None:
    """generate() doesn't validate strategy; the CLI does. But the type system requires Literal."""
    inv = make_inventory(green_mapping())
    plan = generate(inv, strategy="append")
    assert plan.strategy == "append"
    with pytest.raises(Exception):
        # Intentional invalid strategy — CLI normally validates.
        generate(inv, strategy="bogus")  # type: ignore[arg-type]
