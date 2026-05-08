"""Wire `audit` CLI command to discovery + renderer."""

from __future__ import annotations

from pathlib import Path

from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.aws.eks import BotoEksClient
from eks_identity_migrator.aws.iam import BotoIamClient
from eks_identity_migrator.aws.session import make_session
from eks_identity_migrator.aws.sts import BotoStsClient
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.k8s.client import KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config


def run(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    out: str | None,
    namespace: str | None = None,
    service_account: str | None = None,
) -> ExitCode:
    """Production wire-up of the audit command. Returns the appropriate ExitCode."""
    from rich.console import Console

    from eks_identity_migrator.aws.errors import AwsOperationError
    from eks_identity_migrator.k8s.errors import K8sOperationError
    from eks_identity_migrator.output.json_render import inventory_to_json
    from eks_identity_migrator.output.table import render_inventory_table

    session = make_session(region=region, profile=profile)
    eks = BotoEksClient(session)
    iam = BotoIamClient(session)
    sts = BotoStsClient(session)
    load_kube_config()
    k8s = KubernetesClient()

    try:
        inventory = discover(
            eks=eks,
            iam=iam,
            sts=sts,
            k8s=k8s,
            cluster_name=cluster,
            namespace=namespace,
            service_account=service_account,
        )
    except AwsOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR
    except K8sOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.K8S_ERROR

    Console().print(render_inventory_table(inventory))

    if out:
        Path(out).write_text(inventory_to_json(inventory))

    return ExitCode.OK
