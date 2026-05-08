"""Rollback tests — apply→rollback round-trips state to original."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eks_identity_migrator.apply import association as assoc_mod
from eks_identity_migrator.apply import cleanup as cleanup_mod
from eks_identity_migrator.apply import trust as trust_mod
from eks_identity_migrator.apply.runner import run_phase
from eks_identity_migrator.aws.eks import ClusterInfo
from eks_identity_migrator.journal.writer import JournalWriter
from eks_identity_migrator.k8s.client import IRSA_ANNOTATION
from eks_identity_migrator.policy.canonicalizer import policies_equivalent
from eks_identity_migrator.policy.translator import translate
from eks_identity_migrator.rollback.inverses import (
    CorruptedJournalError,
    invert_iam_update_assume_role_policy,
)
from eks_identity_migrator.rollback.journal_walker import rollback
from eks_identity_migrator.types import (
    AssociationSpec,
    ClusterRef,
    JournalEntry,
    JournalOp,
    JournalStatus,
    Plan,
    PlanStep,
    RiskClassification,
    SARef,
)
from tests.fakes import FakeEksClient, FakeIamClient, FakeK8sClient

FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "trust-policies"
CLUSTER_REF = ClusterRef(
    name="my-cluster",
    region="us-west-2",
    account="123456789012",
    oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
    arn="arn:aws:eks:us-west-2:123456789012:cluster/my-cluster",
)


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def make_plan(role_arn: str = "arn:aws:iam::123456789012:role/app") -> Plan:
    before = load("00a_green_minimum.in.json")
    after = translate(
        before,
        strategy="append",
        cluster_arn=CLUSTER_REF.arn,
        account=CLUSTER_REF.account,
        sa_name="app-frontend",
    )
    return Plan(
        cluster=CLUSTER_REF,
        strategy="append",
        generated_at=datetime(2026, 5, 8, 14, 32, tzinfo=UTC),
        steps=[
            PlanStep(
                sa=SARef(namespace="production", name="app-frontend"),
                role_arn=role_arn,
                risk=RiskClassification.GREEN,
                trust_policy_before=before,
                trust_policy_after=after,
                association_create=AssociationSpec(
                    cluster_name=CLUSTER_REF.name,
                    namespace="production",
                    service_account="app-frontend",
                    role_arn=role_arn,
                ),
            )
        ],
    )


def test_trust_apply_then_rollback_restores_policy(tmp_path: Path) -> None:
    iam = FakeIamClient()
    role_arn = "arn:aws:iam::123456789012:role/app"
    original = load("00a_green_minimum.in.json")
    iam.add_role(role_arn, original)
    plan = make_plan(role_arn)

    journal_path = tmp_path / "j.jsonl"
    writer = JournalWriter(journal_path)
    run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(iam),
        dry_run=False,
        continue_on_error=False,
    )
    # Sanity: the role was mutated.
    assert not policies_equivalent(iam.roles[role_arn].trust_policy, original)

    eks = FakeEksClient()
    k8s = FakeK8sClient()
    result = rollback(str(journal_path), phase="trust", iam=iam, eks=eks, k8s=k8s)
    assert result.failed == 0
    assert result.inverted == 1
    # Policy is restored to its original state.
    assert policies_equivalent(iam.roles[role_arn].trust_policy, original)


def test_association_apply_then_rollback_deletes(tmp_path: Path) -> None:
    eks = FakeEksClient()
    eks.add_cluster(
        ClusterInfo(
            name=CLUSTER_REF.name,
            arn=CLUSTER_REF.arn,
            region=CLUSTER_REF.region,
            account=CLUSTER_REF.account,
            oidc_issuer=CLUSTER_REF.oidc_issuer,
        ),
        addons=["eks-pod-identity-agent"],
    )
    plan = make_plan()
    journal_path = tmp_path / "j.jsonl"
    writer = JournalWriter(journal_path)

    run_phase(
        plan,
        journal=writer,
        handler=assoc_mod.make_handler(eks, plan),
        dry_run=False,
        continue_on_error=False,
    )
    assert len(eks.associations) == 1

    iam = FakeIamClient()
    k8s = FakeK8sClient()
    result = rollback(str(journal_path), phase="association", iam=iam, eks=eks, k8s=k8s)
    assert result.inverted == 1
    assert eks.associations == []


def test_cleanup_apply_then_rollback_restores_annotation(tmp_path: Path) -> None:
    k8s = FakeK8sClient()
    role_arn = "arn:aws:iam::123456789012:role/app"
    k8s.add_sa("production", "app-frontend", annotations={IRSA_ANNOTATION: role_arn})
    plan = make_plan(role_arn)
    journal_path = tmp_path / "j.jsonl"
    writer = JournalWriter(journal_path)

    run_phase(
        plan,
        journal=writer,
        handler=cleanup_mod.make_handler(k8s),
        dry_run=False,
        continue_on_error=False,
    )
    assert IRSA_ANNOTATION not in k8s.service_accounts[0].annotations

    iam = FakeIamClient()
    eks = FakeEksClient()
    result = rollback(str(journal_path), phase="cleanup", iam=iam, eks=eks, k8s=k8s)
    assert result.inverted == 1
    assert k8s.service_accounts[0].annotations[IRSA_ANNOTATION] == role_arn


def test_phase_filter_only_inverts_matching_ops(tmp_path: Path) -> None:
    iam = FakeIamClient()
    role_arn = "arn:aws:iam::123:role/app"
    iam.add_role(role_arn, load("00a_green_minimum.in.json"))
    plan = make_plan(role_arn)

    journal_path = tmp_path / "j.jsonl"
    writer = JournalWriter(journal_path)
    run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(iam),
        dry_run=False,
        continue_on_error=False,
    )
    # Now request rollback for the wrong phase — should do nothing.
    eks = FakeEksClient()
    k8s = FakeK8sClient()
    result = rollback(str(journal_path), phase="cleanup", iam=iam, eks=eks, k8s=k8s)
    assert result.inverted == 0


def test_corrupted_journal_entry_raises_on_invert() -> None:
    bad = JournalEntry(
        ts=datetime.now(UTC),
        op=JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
        status=JournalStatus.SUCCESS,
        sa=SARef(namespace="ns", name="x"),
        role_arn="arn:aws:iam::123:role/x",
        before={},
        after={"policy": {"Version": "2012-10-17"}},
    )
    iam = FakeIamClient()
    iam.add_role("arn:aws:iam::123:role/x", {"Version": "2012-10-17", "Statement": []})
    with pytest.raises(CorruptedJournalError):
        invert_iam_update_assume_role_policy(bad, iam=iam)
