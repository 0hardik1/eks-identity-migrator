"""Wire `rollback` CLI command."""

from __future__ import annotations

from rich.console import Console

from eks_identity_migrator.aws.eks import BotoEksClient
from eks_identity_migrator.aws.iam import BotoIamClient
from eks_identity_migrator.aws.session import make_session
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.k8s.client import KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config
from eks_identity_migrator.rollback.journal_walker import PHASE_OPS, rollback


def run(
    *,
    journal: str,
    phase: str,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    console = Console()
    if phase not in PHASE_OPS:
        Console(stderr=True).print(
            "[red]error:[/red] --phase must be one of trust|association|cleanup"
        )
        return ExitCode.INVALID_INPUT

    session = make_session(region=region, profile=profile)
    iam = BotoIamClient(session)
    eks = BotoEksClient(session)
    load_kube_config()
    k8s = KubernetesClient()

    result = rollback(journal, phase=phase, iam=iam, eks=eks, k8s=k8s)
    console.print(
        f"rollback phase={phase}: {result.inverted} reverted, "
        f"{result.skipped} skipped, {result.failed} failed"
    )
    if result.errors:
        for err in result.errors:
            console.print(f"  [red]✗[/red] {err}")
    return result.exit_code()
