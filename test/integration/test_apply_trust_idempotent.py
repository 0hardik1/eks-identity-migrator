"""End-to-end: apply --phase trust against real LocalStack IAM is idempotent.

Mirrors the tests/apply unit test against a real IAM API. The role is created
in LocalStack, the trust phase mutates it once, and a second invocation
records zero mutations (acceptance §12.4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def role_with_irsa_trust(boto_session_localstack, localstack_iam: str):
    iam = boto_session_localstack.client("iam", endpoint_url=localstack_iam)
    name = "TestRole"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": (
                        "arn:aws:iam::123456789012:oidc-provider/"
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE"
                    )
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:aud": "sts.amazonaws.com",
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub": "system:serviceaccount:prod:app",
                    }
                },
            }
        ],
    }
    iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust))
    return f"arn:aws:iam::000000000000:role/{name}"


def test_trust_phase_idempotent_against_localstack(
    boto_session_localstack, localstack_iam: str, role_with_irsa_trust: str, tmp_path: Path
) -> None:
    """Apply trust twice; second run is a no-op (zero IAM mutations beyond the first)."""
    from eks_identity_migrator.apply.runner import run_phase
    from eks_identity_migrator.apply import trust as trust_mod
    from eks_identity_migrator.aws.iam import BotoIamClient
    from eks_identity_migrator.journal.writer import JournalWriter
    from eks_identity_migrator.journal.reader import read_journal
    from eks_identity_migrator.policy.translator import translate
    from eks_identity_migrator.types import (
        AssociationSpec,
        ClusterRef,
        Plan,
        PlanStep,
        RiskClassification,
        SARef,
    )

    iam = BotoIamClient(boto_session_localstack, endpoint_url=localstack_iam)
    cluster = ClusterRef(
        name="my-cluster",
        region="us-west-2",
        account="000000000000",
        oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
        arn="arn:aws:eks:us-west-2:000000000000:cluster/my-cluster",
    )
    role = iam.get_role(role_with_irsa_trust)
    assert role is not None
    after = translate(
        role.trust_policy,
        strategy="append",
        cluster_arn=cluster.arn,
        account=cluster.account,
        sa_name="app",
    )
    plan = Plan(
        cluster=cluster,
        strategy="append",
        generated_at=datetime(2026, 5, 8, tzinfo=timezone.utc),
        steps=[
            PlanStep(
                sa=SARef(namespace="prod", name="app"),
                role_arn=role_with_irsa_trust,
                risk=RiskClassification.GREEN,
                trust_policy_before=role.trust_policy,
                trust_policy_after=after,
                association_create=AssociationSpec(
                    cluster_name=cluster.name,
                    namespace="prod",
                    service_account="app",
                    role_arn=role_with_irsa_trust,
                ),
            )
        ],
    )

    journal_path = tmp_path / "j.jsonl"
    writer = JournalWriter(journal_path)
    handler = trust_mod.make_handler(iam)

    run_phase(plan, journal=writer, handler=handler, dry_run=False, continue_on_error=False)
    first_journal = read_journal(journal_path)
    success_count_first = sum(1 for e in first_journal if e.status.value == "success")
    assert success_count_first == 1

    journal_path2 = tmp_path / "j2.jsonl"
    writer2 = JournalWriter(journal_path2)
    run_phase(plan, journal=writer2, handler=handler, dry_run=False, continue_on_error=False)
    second_journal = read_journal(journal_path2)
    success_count_second = sum(1 for e in second_journal if e.status.value == "success")
    skipped_count_second = sum(1 for e in second_journal if e.status.value == "skipped")
    # Second run: no successful mutations, just an "already-applied" skip.
    assert success_count_second == 0
    assert skipped_count_second == 1
