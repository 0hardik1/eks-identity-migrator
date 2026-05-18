"""Wire `plan` CLI command.

Discovers the inventory, runs the plan generator, writes ``plan.yaml`` to
``--out``. Strategy is validated upstream (at the CLI layer via
``cli/_validators.py``).
"""

from __future__ import annotations

from typing import cast

from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.cli.setup import make_clients
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

    clients = make_clients(region=region, profile=profile)

    try:
        inventory = discover(
            eks=clients.eks,
            iam=clients.iam,
            sts=clients.sts,
            k8s=clients.k8s,
            cluster_name=cluster,
        )
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
