"""Classifier tests — one per finding code, plus integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eks_identity_migrator.policy.parser import parse_trust_policy, try_parse_trust_policy
from eks_identity_migrator.risk import (
    FindingCode,
    MappingContext,
    PodEnvVar,
    classify,
)
from eks_identity_migrator.types.inventory import RiskClassification

FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "trust-policies"
THIS_ISSUER = "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE"
THIS_CLUSTER_ARN = "arn:aws:eks:us-west-2:123456789012:cluster/my-cluster"
THIS_ACCOUNT = "123456789012"


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def make_ctx(
    *,
    sa_name: str = "app-frontend",
    sa_namespace: str = "production",
    role_account: str | None = None,
    permission_boundary: str | None = None,
    used_by_pods_count: int = 1,
    pod_envs: tuple[PodEnvVar, ...] = (),
    cluster_oidc_issuer: str = THIS_ISSUER,
    cluster_account: str = THIS_ACCOUNT,
) -> MappingContext:
    return MappingContext(
        cluster_name="my-cluster",
        cluster_arn=THIS_CLUSTER_ARN,
        cluster_account=cluster_account,
        cluster_oidc_issuer=cluster_oidc_issuer,
        sa_namespace=sa_namespace,
        sa_name=sa_name,
        role_account=role_account or cluster_account,
        permission_boundary=permission_boundary,
        used_by_pods_count=used_by_pods_count,
        pod_envs=pod_envs,
    )


# ---- baseline -------------------------------------------------------------


def test_green_minimum_no_findings() -> None:
    parsed = parse_trust_policy(load("00a_green_minimum.in.json"))
    color, findings = classify(parsed, make_ctx())
    assert color == RiskClassification.GREEN
    assert findings == []


def test_green_with_sid_still_green() -> None:
    parsed = parse_trust_policy(load("00b_green_with_sid.in.json"))
    color, _ = classify(parsed, make_ctx())
    assert color == RiskClassification.GREEN


def test_principal_federated_array_form_classifies_green() -> None:
    parsed = parse_trust_policy(load("00f_principal_federated_array.in.json"))
    color, _ = classify(parsed, make_ctx())
    assert color == RiskClassification.GREEN


def test_replace_safe_single_statement_green() -> None:
    parsed = parse_trust_policy(load("00g_replace_strategy_safe.in.json"))
    color, _ = classify(parsed, make_ctx(sa_name="single-sa"))
    assert color == RiskClassification.GREEN


# ---- gray paths -----------------------------------------------------------


def test_parse_failure_is_gray() -> None:
    parsed = try_parse_trust_policy(load("00d_policy_parse_error.in.json"))
    color, findings = classify(parsed, make_ctx())
    assert color == RiskClassification.GRAY
    assert any(f.code == FindingCode.POLICY_PARSE_ERROR.value for f in findings)


def test_stale_annotation_is_gray() -> None:
    parsed = parse_trust_policy(load("00a_green_minimum.in.json"))
    color, findings = classify(parsed, make_ctx(used_by_pods_count=0))
    assert color == RiskClassification.GRAY
    assert any(f.code == FindingCode.STALE_ANNOTATION.value for f in findings)


# ---- yellow rules ---------------------------------------------------------


def test_multi_cluster_role_reuse_is_yellow() -> None:
    parsed = parse_trust_policy(load("01_multi_cluster_role_reuse.in.json"))
    # Cluster A is "this" cluster; Cluster B's issuer is different.
    ctx = make_ctx(
        cluster_oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/CLUSTERA",
    )
    color, findings = classify(parsed, ctx)
    codes = [f.code for f in findings]
    assert FindingCode.ROLE_USED_BY_MULTIPLE_CLUSTERS.value in codes
    assert FindingCode.MULTI_STATEMENT_OIDC.value in codes
    assert color == RiskClassification.YELLOW


def test_wildcard_sub_is_yellow() -> None:
    parsed = parse_trust_policy(load("03_wildcard_sub.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="some-sa", sa_namespace="foo"))
    assert FindingCode.WILDCARD_SUB.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_forall_multi_sub_is_yellow() -> None:
    parsed = parse_trust_policy(load("04_forall_multi_sub.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="reader", sa_namespace="prod"))
    assert FindingCode.MULTI_SUB_FORALL.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_default_sa_annotated_is_yellow() -> None:
    parsed = parse_trust_policy(load("08_default_sa_annotated.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="default", sa_namespace="legacy"))
    assert FindingCode.DEFAULT_SA_ANNOTATED.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_operator_alb_is_yellow() -> None:
    parsed = parse_trust_policy(load("09a_operator_alb.in.json"))
    color, findings = classify(
        parsed, make_ctx(sa_name="aws-load-balancer-controller", sa_namespace="kube-system")
    )
    assert FindingCode.OPERATOR_MANAGED.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_operator_karpenter_is_yellow() -> None:
    parsed = parse_trust_policy(load("09b_operator_karpenter.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="karpenter", sa_namespace="karpenter"))
    assert FindingCode.OPERATOR_MANAGED.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_operator_ebs_csi_is_yellow() -> None:
    parsed = parse_trust_policy(load("09c_operator_ebs_csi.in.json"))
    color, findings = classify(
        parsed, make_ctx(sa_name="ebs-csi-controller-sa", sa_namespace="kube-system")
    )
    assert FindingCode.OPERATOR_MANAGED.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_session_name_too_long_is_yellow() -> None:
    parsed = parse_trust_policy(load("13_session_name_too_long.in.json"))
    color, findings = classify(
        parsed,
        make_ctx(
            sa_name="extremely-long-service-account-name-that-blows-the-iam-session-limit",
            sa_namespace="very-very-long-namespace-name",
        ),
    )
    assert FindingCode.SESSION_NAME_TOO_LONG.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_mixed_ec2_irsa_is_yellow() -> None:
    parsed = parse_trust_policy(load("14_mixed_ec2_irsa.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="tool", sa_namespace="legacy"))
    assert FindingCode.MIXED_PRINCIPAL_EC2.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_custom_token_file_path_is_yellow() -> None:
    parsed = parse_trust_policy(load("12_custom_token_file_path.in.json"))
    pod_envs = (PodEnvVar(name="AWS_WEB_IDENTITY_TOKEN_FILE", value="/custom/path/token"),)
    color, findings = classify(
        parsed, make_ctx(sa_name="custom-token-app", sa_namespace="apps", pod_envs=pod_envs)
    )
    assert FindingCode.CUSTOM_TOKEN_FILE_PATH.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


def test_default_token_file_path_does_not_trigger() -> None:
    parsed = parse_trust_policy(load("00a_green_minimum.in.json"))
    pod_envs = (
        PodEnvVar(
            name="AWS_WEB_IDENTITY_TOKEN_FILE",
            value="/var/run/secrets/eks.amazonaws.com/serviceaccount/token",
        ),
    )
    color, findings = classify(parsed, make_ctx(pod_envs=pod_envs))
    codes = [f.code for f in findings]
    assert FindingCode.CUSTOM_TOKEN_FILE_PATH.value not in codes
    assert color == RiskClassification.GREEN


def test_multi_statement_oidc_is_yellow() -> None:
    parsed = parse_trust_policy(load("00e_multi_statement_oidc.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="app-frontend"))
    assert FindingCode.MULTI_STATEMENT_OIDC.value in [f.code for f in findings]
    assert color == RiskClassification.YELLOW


# ---- red rules ------------------------------------------------------------


def test_cross_account_trust_is_red() -> None:
    parsed = parse_trust_policy(load("02_cross_account_trust.in.json"))
    ctx = make_ctx(
        sa_name="etl-pipeline",
        sa_namespace="data",
        cluster_account="222222222222",  # different from issuer's 111
        cluster_oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/SOURCEACCT",
    )
    color, findings = classify(parsed, ctx)
    assert FindingCode.CROSS_ACCOUNT_TRUST.value in [f.code for f in findings]
    assert color == RiskClassification.RED


def test_custom_aud_claim_is_red() -> None:
    parsed = parse_trust_policy(load("05_custom_aud_claim.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="vault-agent", sa_namespace="vault"))
    assert FindingCode.CUSTOM_AUD_CLAIM.value in [f.code for f in findings]
    assert color == RiskClassification.RED


def test_foreign_oidc_issuer_is_red() -> None:
    """Trust policy references issuer X; cluster's issuer is Y."""
    parsed = parse_trust_policy(load("00a_green_minimum.in.json"))
    ctx = make_ctx(
        cluster_oidc_issuer="https://oidc.eks.us-east-1.amazonaws.com/id/OTHERCLUSTER",
    )
    color, findings = classify(parsed, ctx)
    assert FindingCode.FOREIGN_OIDC_ISSUER.value in [f.code for f in findings]
    assert color == RiskClassification.RED


# ---- informational --------------------------------------------------------


def test_permission_boundary_does_not_change_color() -> None:
    parsed = parse_trust_policy(load("06_permission_boundary.in.json"))
    color, findings = classify(
        parsed,
        make_ctx(
            sa_name="bounded-app",
            sa_namespace="secure",
            permission_boundary="arn:aws:iam::123456789012:policy/MyBoundary",
        ),
    )
    assert FindingCode.PERMISSION_BOUNDARY.value in [f.code for f in findings]
    assert color == RiskClassification.GREEN


def test_tagsession_present_is_informational_no_color_change() -> None:
    parsed = parse_trust_policy(load("15_tagsession_already_present.in.json"))
    color, findings = classify(parsed, make_ctx(sa_name="app-frontend"))
    assert FindingCode.STS_TAGSESSION_PRESENT.value in [f.code for f in findings]
    assert color == RiskClassification.GREEN


# ---- precedence -----------------------------------------------------------


def test_red_beats_yellow_when_both_present() -> None:
    """Cross-account + wildcard sub: red wins."""
    # Build a policy with both characteristics.
    policy: dict[str, object] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::999999999999:role/external"},
                "Action": "sts:AssumeRole",
            },
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
                    "StringLike": {
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub": "system:serviceaccount:foo:*"
                    }
                },
            },
        ],
    }
    parsed = parse_trust_policy(policy)
    color, _ = classify(parsed, make_ctx(sa_name="bar", sa_namespace="foo"))
    assert color == RiskClassification.RED


@pytest.mark.parametrize(
    "code",
    [
        FindingCode.ROLE_USED_BY_MULTIPLE_CLUSTERS,
        FindingCode.CROSS_ACCOUNT_TRUST,
        FindingCode.WILDCARD_SUB,
        FindingCode.MULTI_SUB_FORALL,
        FindingCode.CUSTOM_AUD_CLAIM,
        FindingCode.PERMISSION_BOUNDARY,
        FindingCode.STALE_ANNOTATION,
        FindingCode.DEFAULT_SA_ANNOTATED,
        FindingCode.OPERATOR_MANAGED,
        FindingCode.MIXED_PRINCIPAL_EC2,
        FindingCode.SESSION_NAME_TOO_LONG,
        FindingCode.STS_TAGSESSION_PRESENT,
        FindingCode.MULTI_STATEMENT_OIDC,
        FindingCode.POLICY_PARSE_ERROR,
        FindingCode.CUSTOM_TOKEN_FILE_PATH,
        FindingCode.FOREIGN_OIDC_ISSUER,
    ],
)
def test_finding_code_exists(code: FindingCode) -> None:
    """All gotcha-mapped finding codes must exist as enum members."""
    assert code.value in [c.value for c in FindingCode]
