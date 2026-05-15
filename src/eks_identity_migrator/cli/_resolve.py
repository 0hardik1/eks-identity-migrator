"""Resolve a cluster name + region from the current kubectl context.

Used by `audit`, `plan`, and `migrate` to support the zero-arg quickstart
(``make scan``). When the user passes ``--cluster X`` we honour it as-is.
When they don't, we read the active kubeconfig context, parse the cluster
name + region hint out of it, and announce what we picked so the user can
abort if it's not the cluster they meant.

Output convention: the auto-detect banner is written to **stderr** — keeps
``--out`` and pipe-to-jq workflows clean.
"""

from __future__ import annotations

import typer
from rich.console import Console

from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.k8s.config import (
    KubeContextResolutionError,
    get_current_context_hint,
)


def resolve_cluster(
    cluster: str | None,
    region: str | None,
    *,
    kubeconfig: str | None = None,
) -> tuple[str, str | None]:
    """Return ``(cluster, region)``, auto-detecting from kubeconfig when needed.

    - Explicit ``cluster`` ⇒ pass-through (silent).
    - Missing ``cluster`` ⇒ infer from active kubectl context.
    - Explicit ``region`` always wins over the hint's region.
    - On resolution failure we raise ``typer.Exit(INVALID_INPUT)`` after
      printing an educational error to stderr.
    """
    if cluster:
        return cluster, region

    err = Console(stderr=True)
    try:
        hint = get_current_context_hint(kubeconfig=kubeconfig)
    except KubeContextResolutionError as exc:
        err.print(f"[red]error:[/red] {exc}")
        err.print(
            "[dim]hint: pass `--cluster <name>` explicitly, or run "
            "`aws eks update-kubeconfig --name <cluster>` first.[/dim]"
        )
        raise typer.Exit(code=int(ExitCode.INVALID_INPUT)) from exc

    chosen_region = region or hint.region
    region_note = f" region={chosen_region}" if chosen_region else ""
    err.print(
        f"[dim]auto-detected cluster=[/dim][cyan]{hint.cluster_name}[/cyan]"
        f"[dim]{region_note} from kubectl context [/dim][cyan]{hint.context_name}[/cyan]"
    )
    return hint.cluster_name, chosen_region
