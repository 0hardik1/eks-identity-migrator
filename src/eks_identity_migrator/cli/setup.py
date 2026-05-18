"""Shared AWS + K8s client factory used by audit, plan, and migrate.

These three commands always build the same four AWS clients (session, iam,
eks, sts) plus a K8s client. Putting the construction here removes ~30 lines
of identical setup from each entry point.

This file straddles the AWS/K8s boundary, but it never imports ``boto3`` or
``kubernetes`` directly — it calls the factory functions from those modules.
``tests/test_imports.py`` enforces that rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from eks_identity_migrator.aws.eks import BotoEksClient, EksClient
from eks_identity_migrator.aws.iam import BotoIamClient, IamClient
from eks_identity_migrator.aws.session import make_session
from eks_identity_migrator.aws.sts import BotoStsClient, StsClient
from eks_identity_migrator.k8s.client import K8sClient, KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config


@dataclass(frozen=True)
class Clients:
    """The AWS + K8s clients needed by discovery/plan/migrate."""

    iam: IamClient
    eks: EksClient
    sts: StsClient
    k8s: K8sClient


def make_clients(
    *,
    region: str | None,
    profile: str | None,
    kubeconfig: str | None = None,
    context: str | None = None,
) -> Clients:
    """Build the four clients in one place.

    ``region`` and ``profile`` flow into ``make_session()``; when both are
    ``None`` boto3's default config chain (env vars, ``~/.aws/config``) takes
    over. ``kubeconfig`` and ``context`` are forwarded to ``load_kube_config()``
    before constructing ``KubernetesClient``.
    """
    session = make_session(region=region, profile=profile)
    iam = BotoIamClient(session)
    eks = BotoEksClient(session)
    sts = BotoStsClient(session)

    load_kube_config(kubeconfig=kubeconfig, context=context)
    k8s = KubernetesClient()

    return Clients(iam=iam, eks=eks, sts=sts, k8s=k8s)
