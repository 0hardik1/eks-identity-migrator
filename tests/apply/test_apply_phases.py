"""Apply phase tests against in-memory fakes."""

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
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.journal.reader import read_journal
from eks_identity_migrator.journal.writer import JournalWriter
from eks_identity_migrator.k8s.client import IRSA_ANNOTATION
from eks_identity_migrator.policy.translator import translate
from eks_identity_migrator.types import (
    AssociationSpec,
    ClusterRef,
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


def green_step(role_arn: str = "arn:aws:iam::123456789012:role/app") -> PlanStep:
    before = load("00a_green_minimum.in.json")
    after = translate(
        before,
        strategy="append",
        cluster_arn=CLUSTER_REF.arn,
        account=CLUSTER_REF.account,
        sa_name="app-frontend",
    )
    return PlanStep(
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


def make_plan(*steps: PlanStep) -> Plan:
    return Plan(
        cluster=CLUSTER_REF,
        strategy="append",
        generated_at=datetime(2026, 5, 8, 14, 32, tzinfo=UTC),
        steps=list(steps),
    )


# ---- trust phase ---------------------------------------------------------


def test_trust_applies_then_skips_on_rerun(tmp_path: Path) -> None:
    iam = FakeIamClient()
    role_arn = "arn:aws:iam::123456789012:role/app"
    iam.add_role(role_arn, load("00a_green_minimum.in.json"))
    plan = make_plan(green_step(role_arn))

    writer = JournalWriter(tmp_path / "j.jsonl")
    handler = trust_mod.make_handler(iam)

    r1 = run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    assert r1.succeeded == 1
    assert r1.failed == 0

    # Same plan, same fakes → already-applied → skipped, no extra IAM call.
    r2 = run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    assert r2.succeeded == 0
    assert r2.skipped + r2.succeeded == 1  # outcome.SKIPPED counts as skipped
    # Mutation count should remain at 1 from the first run.
    assert len(iam.update_calls) == 1


def test_trust_idempotent_three_runs(tmp_path: Path) -> None:
    """Spec acceptance §12.4: rerun produces same end state, second run records 0 mutations."""
    iam = FakeIamClient()
    role_arn = "arn:aws:iam::123456789012:role/app"
    iam.add_role(role_arn, load("00a_green_minimum.in.json"))
    plan = make_plan(green_step(role_arn))

    handler = trust_mod.make_handler(iam)
    for _ in range(3):
        writer = JournalWriter(tmp_path / "j.jsonl")
        run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    assert len(iam.update_calls) == 1  # first run only


def test_trust_dry_run_makes_no_iam_calls(tmp_path: Path) -> None:
    iam = FakeIamClient()
    role_arn = "arn:aws:iam::123456789012:role/app"
    iam.add_role(role_arn, load("00a_green_minimum.in.json"))
    plan = make_plan(green_step(role_arn))
    writer = JournalWriter(tmp_path / "j.jsonl")

    run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(iam),
        dry_run=True,
        continue_on_error=False,
    )
    assert iam.update_calls == []
    # Journal records the would-be op as pending.
    entries = read_journal(tmp_path / "j.jsonl")
    assert all(e.status == JournalStatus.PENDING for e in entries)


def test_trust_failure_recorded_in_journal(tmp_path: Path) -> None:
    iam = FakeIamClient()
    # No role added — get_role returns None, handler should record failure.
    plan = make_plan(green_step("arn:aws:iam::123456789012:role/missing"))
    writer = JournalWriter(tmp_path / "j.jsonl")

    result = run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(iam),
        dry_run=False,
        continue_on_error=False,
    )
    assert result.failed == 1
    entries = read_journal(tmp_path / "j.jsonl")
    assert entries[-1].status == JournalStatus.FAILURE


# ---- association phase ---------------------------------------------------


def test_association_preflight_addon_missing_raises() -> None:
    eks = FakeEksClient()
    eks.add_cluster(
        ClusterInfo(
            name="c",
            arn="arn:aws:eks:us-west-2:123:cluster/c",
            region="us-west-2",
            account="123",
            oidc_issuer="https://x/y",
        ),
        addons=[],
    )
    with pytest.raises(assoc_mod.PodIdentityAgentMissingError):
        assoc_mod.preflight_addon(eks, "c")


def test_association_preflight_addon_present_passes() -> None:
    eks = FakeEksClient()
    eks.add_cluster(
        ClusterInfo(
            name="c",
            arn="arn:aws:eks:us-west-2:123:cluster/c",
            region="us-west-2",
            account="123",
            oidc_issuer="https://x/y",
        ),
        addons=["eks-pod-identity-agent"],
    )
    assoc_mod.preflight_addon(eks, "c")  # should not raise


def test_association_creates_then_skips_on_rerun(tmp_path: Path) -> None:
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
    plan = make_plan(green_step())
    writer = JournalWriter(tmp_path / "j.jsonl")
    handler = assoc_mod.make_handler(eks, plan)

    r1 = run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    assert r1.succeeded == 1
    assert len(eks.create_calls) == 1

    # Re-run -> existing association with same role -> skipped.
    r2 = run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    assert len(eks.create_calls) == 1


def test_association_existing_different_role_errors(tmp_path: Path) -> None:
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
    # Pre-create an association pointing to a different role.
    eks.create_pod_identity_association(
        cluster_name=CLUSTER_REF.name,
        namespace="production",
        service_account="app-frontend",
        role_arn="arn:aws:iam::123456789012:role/SOME_OTHER",
    )
    plan = make_plan(green_step("arn:aws:iam::123456789012:role/app"))
    writer = JournalWriter(tmp_path / "j.jsonl")
    handler = assoc_mod.make_handler(eks, plan)

    result = run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=True)
    assert result.failed == 1
    assert result.errors is not None
    assert "different role" in result.errors[0].lower() or "expected" in result.errors[0].lower()


# ---- cleanup phase -------------------------------------------------------


def test_cleanup_removes_annotation(tmp_path: Path) -> None:
    k8s = FakeK8sClient()
    k8s.add_sa(
        "production",
        "app-frontend",
        annotations={IRSA_ANNOTATION: "arn:aws:iam::123:role/app"},
    )
    plan = make_plan(green_step())
    writer = JournalWriter(tmp_path / "j.jsonl")
    handler = cleanup_mod.make_handler(k8s)

    run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    assert IRSA_ANNOTATION not in k8s.service_accounts[0].annotations
    # Journal records the removal with the prior value for rollback.
    entries = read_journal(tmp_path / "j.jsonl")
    assert entries[-1].before["value"] is not None


def test_cleanup_remove_oidc_trust_strips_oidc_statements(tmp_path: Path) -> None:
    k8s = FakeK8sClient()
    iam = FakeIamClient()
    role_arn = "arn:aws:iam::123456789012:role/app"
    # Initial trust policy has both OIDC and Pod Identity statements (post-trust phase).
    initial = translate(
        load("00a_green_minimum.in.json"),
        strategy="append",
        cluster_arn=CLUSTER_REF.arn,
        account=CLUSTER_REF.account,
        sa_name="app-frontend",
    )
    iam.add_role(role_arn, initial)
    k8s.add_sa(
        "production",
        "app-frontend",
        annotations={IRSA_ANNOTATION: role_arn},
    )
    plan = make_plan(green_step(role_arn))
    writer = JournalWriter(tmp_path / "j.jsonl")
    handler = cleanup_mod.make_handler(k8s, iam=iam, remove_oidc_trust=True)

    run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    after = iam.roles[role_arn].trust_policy
    has_oidc = any(
        isinstance(s, dict)
        and isinstance(s.get("Principal"), dict)
        and "Federated" in s["Principal"]
        for s in after["Statement"]
    )
    assert not has_oidc


# ---- exit-code mapping ---------------------------------------------------


def test_exit_code_ok_when_only_skipped_and_succeeded() -> None:
    iam = FakeIamClient()
    iam.add_role("arn:aws:iam::123:role/app", load("00a_green_minimum.in.json"))
    # Identical pre-state → handler returns SKIPPED, no failures.
    plan = make_plan(green_step("arn:aws:iam::123:role/app"))
    plan.steps[0].trust_policy_after = plan.steps[0].trust_policy_before
    writer = JournalWriter("/tmp/_apply_test.jsonl")
    Path("/tmp/_apply_test.jsonl").unlink(missing_ok=True)
    result = run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(iam),
        dry_run=False,
        continue_on_error=False,
    )
    assert result.exit_code() == ExitCode.OK
