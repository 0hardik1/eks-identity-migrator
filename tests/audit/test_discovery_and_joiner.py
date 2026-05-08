"""Audit module — discovery + joiner against in-memory fakes."""

from __future__ import annotations

import json
from pathlib import Path

from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.aws.eks import ClusterInfo
from eks_identity_migrator.k8s.client import IRSA_ANNOTATION
from eks_identity_migrator.risk.codes import FindingCode
from eks_identity_migrator.types.inventory import RiskClassification
from tests.fakes import FakeEksClient, FakeIamClient, FakeK8sClient, FakeStsClient

FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "trust-policies"
CLUSTER = ClusterInfo(
    name="my-cluster",
    arn="arn:aws:eks:us-west-2:123456789012:cluster/my-cluster",
    region="us-west-2",
    account="123456789012",
    oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
)


def make_clients() -> tuple[FakeEksClient, FakeIamClient, FakeStsClient, FakeK8sClient]:
    eks = FakeEksClient()
    eks.add_cluster(CLUSTER, addons=["eks-pod-identity-agent"])
    return eks, FakeIamClient(), FakeStsClient(), FakeK8sClient()


def load_policy(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_audit_green_minimum() -> None:
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/frontend"
    iam.add_role(role_arn, load_policy("00a_green_minimum.in.json"))
    k8s.add_sa("production", "app-frontend", annotations={IRSA_ANNOTATION: role_arn})
    k8s.add_pod("production", "frontend-7d-abc", sa="app-frontend", owner="ReplicaSet/frontend-7d")

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert len(inv.mappings) == 1
    m = inv.mappings[0]
    assert m.risk == RiskClassification.GREEN
    assert m.role_arn == role_arn
    assert len(m.used_by_pods) == 1
    assert inv.cluster.account == "123456789012"


def test_audit_role_not_found_is_gray() -> None:
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/missing"
    k8s.add_sa("apps", "deleted", annotations={IRSA_ANNOTATION: role_arn})
    k8s.add_pod("apps", "deleted-x", sa="deleted")

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert len(inv.mappings) == 1
    m = inv.mappings[0]
    assert m.risk == RiskClassification.GRAY
    assert any(f.code == FindingCode.ROLE_NOT_FOUND.value for f in m.findings)


def test_audit_stale_annotation_no_pods_uses_sa() -> None:
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/unused"
    iam.add_role(role_arn, load_policy("00a_green_minimum.in.json"))
    k8s.add_sa("apps", "ghost", annotations={IRSA_ANNOTATION: role_arn})
    # No pod uses 'ghost'.

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert len(inv.mappings) == 1
    m = inv.mappings[0]
    assert m.risk == RiskClassification.GRAY
    assert any(f.code == FindingCode.STALE_ANNOTATION.value for f in m.findings)
    assert any(s.name == "ghost" for s in inv.stale_annotations)


def test_audit_default_sa_picked_up_by_empty_serviceaccountname() -> None:
    """A pod with serviceAccountName="" should be attributed to the namespace `default` SA."""
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/legacy"
    iam.add_role(role_arn, load_policy("08_default_sa_annotated.in.json"))
    k8s.add_sa("legacy", "default", annotations={IRSA_ANNOTATION: role_arn})
    # Pod with no SA → defaults to 'default'.
    k8s.add_pod("legacy", "implicit-default-pod", sa="default")

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    m = inv.mappings[0]
    assert m.sa.name == "default"
    assert len(m.used_by_pods) == 1
    assert any(f.code == FindingCode.DEFAULT_SA_ANNOTATED.value for f in m.findings)


def test_audit_filters_to_namespace() -> None:
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/frontend"
    iam.add_role(role_arn, load_policy("00a_green_minimum.in.json"))
    k8s.add_sa("production", "app-frontend", annotations={IRSA_ANNOTATION: role_arn})
    k8s.add_pod("production", "p1", sa="app-frontend")
    k8s.add_sa("other", "other-app", annotations={IRSA_ANNOTATION: role_arn})
    k8s.add_pod("other", "o1", sa="other-app")

    inv = discover(
        eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster", namespace="production"
    )
    assert len(inv.mappings) == 1
    assert inv.mappings[0].sa.namespace == "production"


def test_audit_skips_unannotated_sas() -> None:
    eks, iam, sts, k8s = make_clients()
    k8s.add_sa("apps", "no-irsa", annotations={"other": "value"})
    k8s.add_pod("apps", "p1", sa="no-irsa")

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert inv.mappings == []


def test_audit_falls_back_to_sts_when_account_empty() -> None:
    eks = FakeEksClient()
    eks.add_cluster(
        ClusterInfo(
            name="my-cluster",
            arn="arn:aws:eks:us-west-2::cluster/my-cluster",
            region="us-west-2",
            account="",
            oidc_issuer="https://oidc.example/id/X",
        ),
        addons=[],
    )
    iam = FakeIamClient()
    sts = FakeStsClient(account="999988887777")
    k8s = FakeK8sClient()

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert inv.cluster.account == "999988887777"


def test_audit_owner_walk_for_pods() -> None:
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/frontend"
    iam.add_role(role_arn, load_policy("00a_green_minimum.in.json"))
    k8s.add_sa("production", "app-frontend", annotations={IRSA_ANNOTATION: role_arn})
    k8s.add_pod("production", "frontend-1", sa="app-frontend", owner="ReplicaSet/frontend-7d")
    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert inv.mappings[0].used_by_pods[0].owner == "ReplicaSet/frontend-7d"


def test_audit_red_for_cross_account() -> None:
    eks, iam, sts, k8s = make_clients()
    role_arn = "arn:aws:iam::123456789012:role/etl"
    # Cross-account: cluster account is 123, federated principal account is 111.
    iam.add_role(role_arn, load_policy("02_cross_account_trust.in.json"))
    k8s.add_sa("data", "etl-pipeline", annotations={IRSA_ANNOTATION: role_arn})
    k8s.add_pod("data", "etl-1", sa="etl-pipeline")

    inv = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name="my-cluster")
    m = inv.mappings[0]
    assert m.risk == RiskClassification.RED
    assert any(f.code == FindingCode.CROSS_ACCOUNT_TRUST.value for f in m.findings)
