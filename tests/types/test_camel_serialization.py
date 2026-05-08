"""Verify pydantic models emit camelCase JSON matching the spec examples."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from eks_identity_migrator.types import (
    AnnotationCleanup,
    AssociationSpec,
    ClusterRef,
    FindingModel,
    Inventory,
    JournalEntry,
    JournalOp,
    JournalStatus,
    Mapping,
    Plan,
    PlanStep,
    PodRef,
    RiskClassification,
    SARef,
)

CLUSTER = ClusterRef(
    name="my-cluster",
    region="us-west-2",
    account="123456789012",
    oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
    arn="arn:aws:eks:us-west-2:123456789012:cluster/my-cluster",
)


def test_cluster_ref_camel_alias() -> None:
    data = json.loads(CLUSTER.model_dump_json(by_alias=True))
    assert data["oidcIssuer"].startswith("https://")
    assert "oidc_issuer" not in data


def test_mapping_camel_aliases() -> None:
    m = Mapping(
        sa=SARef(namespace="prod", name="frontend"),
        role_arn="arn:aws:iam::123456789012:role/frontend",
        trust_policy={"Version": "2012-10-17", "Statement": []},
        used_by_pods=[PodRef(namespace="prod", name="frontend-7d", owner="Deployment/frontend")],
        risk=RiskClassification.GREEN,
    )
    data = json.loads(m.model_dump_json(by_alias=True))
    assert "roleArn" in data
    assert "trustPolicy" in data
    assert "usedByPods" in data
    assert data["risk"] == "green"


def test_finding_serialization() -> None:
    f = FindingModel(code="WILDCARD_SUB", severity="warn", message="...", hint="bind per SA.")
    data = json.loads(f.model_dump_json(by_alias=True))
    assert data == {
        "code": "WILDCARD_SUB",
        "severity": "warn",
        "message": "...",
        "hint": "bind per SA.",
    }


def test_inventory_round_trip() -> None:
    inv = Inventory(
        cluster=CLUSTER,
        generated_at=datetime(2026, 5, 8, 14, 32, tzinfo=UTC),
        mappings=[],
    )
    data = inv.model_dump_json(by_alias=True)
    inv2 = Inventory.model_validate_json(data)
    assert inv2 == inv


def test_plan_step_camel_aliases() -> None:
    step = PlanStep(
        sa=SARef(namespace="prod", name="frontend"),
        role_arn="arn:aws:iam::123456789012:role/frontend",
        risk=RiskClassification.GREEN,
        association_create=AssociationSpec(
            cluster_name="my-cluster",
            namespace="prod",
            service_account="frontend",
            role_arn="arn:aws:iam::123456789012:role/frontend",
        ),
        annotation_cleanup=AnnotationCleanup(
            namespace="prod",
            service_account="frontend",
        ),
    )
    data = json.loads(step.model_dump_json(by_alias=True))
    assert data["roleArn"] == "arn:aws:iam::123456789012:role/frontend"
    assert data["trustPolicyBefore"] == {}
    assert data["trustPolicyAfter"] == {}
    assert data["associationCreate"]["clusterName"] == "my-cluster"
    assert data["annotationCleanup"]["annotationKey"] == "eks.amazonaws.com/role-arn"


def test_plan_round_trip() -> None:
    plan = Plan(
        cluster=CLUSTER,
        strategy="append",
        generated_at=datetime(2026, 5, 8, 14, 32, tzinfo=UTC),
        steps=[],
    )
    blob = plan.model_dump_json(by_alias=True)
    parsed = Plan.model_validate_json(blob)
    assert parsed == plan


def test_journal_entry_camel_aliases() -> None:
    entry = JournalEntry(
        ts=datetime(2026, 5, 8, 14, 35, 1, tzinfo=UTC),
        op=JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
        status=JournalStatus.SUCCESS,
        sa=SARef(namespace="prod", name="frontend"),
        role_arn="arn:aws:iam::123456789012:role/frontend",
        before={"policy": {"Version": "2012-10-17"}},
        after={"policy": {"Version": "2012-10-17", "Statement": [{"Sid": "PI"}]}},
    )
    data = json.loads(entry.model_dump_json(by_alias=True))
    assert data["op"] == "iam:UpdateAssumeRolePolicy"
    assert data["status"] == "success"
    assert data["roleArn"].startswith("arn:")


def test_str_enum_serializes_to_string() -> None:
    assert RiskClassification.GREEN.value == "green"
    assert json.dumps({"risk": RiskClassification.GREEN}) == '{"risk": "green"}'


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValueError):
        SARef.model_validate({"namespace": "prod", "name": "x", "extra": True})


def test_sa_ref_str() -> None:
    assert str(SARef(namespace="prod", name="frontend")) == "prod/frontend"
