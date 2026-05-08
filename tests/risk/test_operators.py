"""Operator-SA registry tests."""

from __future__ import annotations

import pytest

from eks_identity_migrator.risk.operators import is_operator_sa, operator_hint


@pytest.mark.parametrize(
    "name",
    [
        "aws-load-balancer-controller",
        "cluster-autoscaler",
        "karpenter",
        "external-dns",
        "ebs-csi-controller-sa",
        "external-secrets",
        "efs-csi-node-sa",
        "efs-csi-controller-sa",
    ],
)
def test_known_operator_sas_match(name: str) -> None:
    assert is_operator_sa(name)
    assert operator_hint(name) is not None


@pytest.mark.parametrize("name", ["app-frontend", "etl-pipeline", "default", "my-worker"])
def test_unknown_sas_do_not_match(name: str) -> None:
    assert not is_operator_sa(name)
    assert operator_hint(name) is None
