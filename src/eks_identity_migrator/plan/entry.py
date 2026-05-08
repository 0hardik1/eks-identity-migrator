"""Wire `plan` CLI command."""

from __future__ import annotations

from typing import cast

from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.aws.eks import BotoEksClient
from eks_identity_migrator.aws.iam import BotoIamClient
from eks_identity_migrator.aws.session import make_session
from eks_identity_migrator.aws.sts import BotoStsClient
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.k8s.client import KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config
from eks_identity_migrator.plan.generator import generate
from eks_identity_migrator.plan.io import write_plan
from eks_identity_migrator.policy.translator import Strategy


def run(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    strategy: str,
    include_yellow: bool,
    out: str,
) -> ExitCode:
    from rich.console import Console

    from eks_identity_migrator.aws.errors import AwsOperationError
    from eks_identity_migrator.k8s.errors import K8sOperationError

    if strategy not in {"append", "replace"}:
        Console(stderr=True).print("[red]error:[/red] --strategy must be 'append' or 'replace'")
        return ExitCode.INVALID_INPUT

    session = make_session(region=region, profile=profile)
    eks = BotoEksClient(session)
    iam = BotoIamClient(session)
    sts = BotoStsClient(session)
    load_kube_config()
    k8s = KubernetesClient()

    try:
        inventory = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name=cluster)
    except AwsOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR
    except K8sOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.K8S_ERROR

    plan = generate(inventory, strategy=cast(Strategy, strategy), include_yellow=include_yellow)
    write_plan(plan, out)
    Console().print(f"Wrote plan with {len(plan.steps)} steps to {out}")
    return ExitCode.OK
