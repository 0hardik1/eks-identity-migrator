"""Verify tests against the FakeK8sClient."""

from __future__ import annotations

from datetime import UTC, datetime

from eks_identity_migrator.types import (
    AssociationSpec,
    ClusterRef,
    Plan,
    PlanStep,
    RiskClassification,
    SARef,
)
from eks_identity_migrator.verify.probe import verify
from eks_identity_migrator.verify.result import VerifyStatus
from tests.fakes import FakeK8sClient

CLUSTER = ClusterRef(
    name="my-cluster",
    region="us-west-2",
    account="123456789012",
    oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EX",
    arn="arn:aws:eks:us-west-2:123456789012:cluster/my-cluster",
)


def make_plan(*sas: tuple[str, str]) -> Plan:
    steps = []
    for ns, name in sas:
        steps.append(
            PlanStep(
                sa=SARef(namespace=ns, name=name),
                role_arn=f"arn:aws:iam::123456789012:role/{name}",
                risk=RiskClassification.GREEN,
                association_create=AssociationSpec(
                    cluster_name=CLUSTER.name,
                    namespace=ns,
                    service_account=name,
                    role_arn=f"arn:aws:iam::123456789012:role/{name}",
                ),
            )
        )
    return Plan(
        cluster=CLUSTER,
        strategy="append",
        generated_at=datetime(2026, 5, 8, tzinfo=UTC),
        steps=steps,
    )


def test_pod_identity_only_classified_correctly() -> None:
    k8s = FakeK8sClient()
    k8s.add_pod(
        "prod",
        "p1",
        sa="app",
        envs={
            "main": [
                ("AWS_CONTAINER_CREDENTIALS_FULL_URI", "http://169.254.170.23/...", None),
                ("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE", "/var/run/...", None),
            ]
        },
    )
    plan = make_plan(("prod", "app"))
    r = verify(plan, k8s=k8s)
    assert r.entries[0].status == VerifyStatus.POD_IDENTITY


def test_irsa_only_classified_correctly() -> None:
    k8s = FakeK8sClient()
    k8s.add_pod(
        "prod",
        "p1",
        sa="app",
        envs={
            "main": [
                (
                    "AWS_WEB_IDENTITY_TOKEN_FILE",
                    "/var/run/secrets/eks.amazonaws.com/serviceaccount/token",
                    None,
                ),
                ("AWS_ROLE_ARN", "arn:aws:iam::123:role/app", None),
            ]
        },
    )
    plan = make_plan(("prod", "app"))
    r = verify(plan, k8s=k8s)
    assert r.entries[0].status == VerifyStatus.IRSA
    assert r.has_remaining_irsa()


def test_dual_classified() -> None:
    k8s = FakeK8sClient()
    k8s.add_pod(
        "prod",
        "p1",
        sa="app",
        envs={
            "main": [
                ("AWS_WEB_IDENTITY_TOKEN_FILE", "/var/run/...", None),
                ("AWS_CONTAINER_CREDENTIALS_FULL_URI", "http://...", None),
            ]
        },
    )
    plan = make_plan(("prod", "app"))
    r = verify(plan, k8s=k8s)
    assert r.entries[0].status == VerifyStatus.DUAL


def test_pending_pod_is_deferred() -> None:
    k8s = FakeK8sClient()
    k8s.add_pod("prod", "p1", sa="app", phase="Pending")
    plan = make_plan(("prod", "app"))
    r = verify(plan, k8s=k8s)
    assert r.entries[0].status == VerifyStatus.DEFERRED


def test_skipped_steps_not_verified() -> None:
    k8s = FakeK8sClient()
    plan = make_plan(("prod", "app"))
    plan.steps[0].skip = True
    r = verify(plan, k8s=k8s)
    assert r.entries == []
