"""End-to-end: audit a kind cluster with one annotated SA + role in LocalStack."""

from __future__ import annotations

import json
import subprocess
import textwrap

import pytest

pytestmark = pytest.mark.integration


def _kubectl_apply(kubeconfig: str, manifest: str) -> None:
    subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
        input=manifest,
        check=True,
        text=True,
    )


def test_audit_discovers_irsa_sa(
    kind_cluster: str, boto_session_localstack, localstack_iam: str
) -> None:
    from eks_identity_migrator.audit.discovery import discover
    from eks_identity_migrator.aws.iam import BotoIamClient

    role_arn = "arn:aws:iam::000000000000:role/Frontend"
    iam_real = boto_session_localstack.client("iam", endpoint_url=localstack_iam)
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": (
                        "arn:aws:iam::000000000000:oidc-provider/"
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE"
                    )
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:aud": "sts.amazonaws.com",
                        "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub": "system:serviceaccount:prod:frontend",
                    }
                },
            }
        ],
    }
    iam_real.create_role(RoleName="Frontend", AssumeRolePolicyDocument=json.dumps(trust))

    manifest = textwrap.dedent(
        f"""\
        apiVersion: v1
        kind: Namespace
        metadata: {{name: prod}}
        ---
        apiVersion: v1
        kind: ServiceAccount
        metadata:
          name: frontend
          namespace: prod
          annotations:
            eks.amazonaws.com/role-arn: {role_arn}
        ---
        apiVersion: apps/v1
        kind: Deployment
        metadata: {{name: frontend, namespace: prod}}
        spec:
          replicas: 1
          selector: {{matchLabels: {{app: frontend}}}}
          template:
            metadata: {{labels: {{app: frontend}}}}
            spec:
              serviceAccountName: frontend
              containers:
              - name: app
                image: busybox
                command: ["sh", "-c", "sleep 36000"]
        """
    )
    _kubectl_apply(kind_cluster, manifest)

    # Use a fake EKS at the Protocol boundary (LocalStack EKS Pod Identity is incomplete).
    from eks_identity_migrator.aws.eks import ClusterInfo
    from tests.fakes import FakeEksClient, FakeStsClient

    eks = FakeEksClient()
    eks.add_cluster(
        ClusterInfo(
            name="my-cluster",
            arn="arn:aws:eks:us-west-2:000000000000:cluster/my-cluster",
            region="us-west-2",
            account="000000000000",
            oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
        )
    )
    sts = FakeStsClient(account="000000000000")

    iam_proto = BotoIamClient(boto_session_localstack, endpoint_url=localstack_iam)

    # Wire the real KubernetesClient against kind.
    from eks_identity_migrator.k8s.client import KubernetesClient
    from eks_identity_migrator.k8s.config import load_kube_config

    load_kube_config(kubeconfig=kind_cluster)
    k8s = KubernetesClient()

    inventory = discover(eks=eks, iam=iam_proto, sts=sts, k8s=k8s, cluster_name="my-cluster")
    assert any(m.sa.namespace == "prod" and m.sa.name == "frontend" for m in inventory.mappings)
