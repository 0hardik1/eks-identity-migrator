"""Wire `audit` CLI command to discovery + renderer.

Reads from EKS + IAM + STS + K8s, builds an :class:`Inventory`, prints a
table, and optionally writes JSON to ``--out``. Returns an :class:`ExitCode`;
the CLI layer maps that to the process exit status.
"""

from __future__ import annotations

from pathlib import Path

from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.cli.setup import make_clients


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

    clients = make_clients(region=region, profile=profile)

    try:
        inventory = discover(
            eks=clients.eks,
            iam=clients.iam,
            sts=clients.sts,
            k8s=clients.k8s,
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
