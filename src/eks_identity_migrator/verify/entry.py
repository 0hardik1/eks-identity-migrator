"""Wire `verify` CLI command."""

from __future__ import annotations

from rich.console import Console

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.k8s.client import KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config
from eks_identity_migrator.plan.io import read_plan
from eks_identity_migrator.verify.probe import render_verify_summary, verify


def run(
    *,
    plan: str,
    probe: bool,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.k8s.errors import K8sOperationError

    console = Console()
    try:
        plan_obj = read_plan(plan)
    except Exception as exc:
        Console(stderr=True).print(f"[red]error:[/red] failed to load plan: {exc}")
        return ExitCode.INVALID_INPUT

    load_kube_config()
    k8s = KubernetesClient()

    try:
        result = verify(plan_obj, k8s=k8s, probe=probe)
    except K8sOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.K8S_ERROR

    console.print(render_verify_summary(result))

    if result.has_failures():
        return ExitCode.PARTIAL
    return ExitCode.OK
