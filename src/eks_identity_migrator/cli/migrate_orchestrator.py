"""`migrate` convenience: green-only end-to-end with verification gates.

This is the long-form orchestrator for ``migrate`` — it threads the three
phases (trust → association → cleanup) plus a ``verify`` gate between
association and cleanup. Strategy validation and cluster resolution happen
in the CLI layer; this file only sees concrete strings.
"""

from __future__ import annotations

from typing import cast

from rich.console import Console

from eks_identity_migrator.apply import association as assoc_mod
from eks_identity_migrator.apply import cleanup as cleanup_mod
from eks_identity_migrator.apply import trust as trust_mod
from eks_identity_migrator.apply.runner import run_phase
from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.cli.setup import make_clients
from eks_identity_migrator.journal.writer import JournalWriter, default_journal_path
from eks_identity_migrator.output import educational
from eks_identity_migrator.plan.generator import generate
from eks_identity_migrator.policy.translator import Strategy
from eks_identity_migrator.types.inventory import RiskClassification
from eks_identity_migrator.verify.probe import render_verify_summary, verify


def run(
    *,
    cluster: str,
    region: str | None,
    profile: str | None,
    strategy: str,
    journal: str | None,
    continue_on_error: bool,
) -> ExitCode:
    from eks_identity_migrator.aws.errors import AwsOperationError
    from eks_identity_migrator.k8s.errors import K8sOperationError

    console = Console()
    err = Console(stderr=True)
    clients = make_clients(region=region, profile=profile)

    try:
        inventory = discover(
            eks=clients.eks,
            iam=clients.iam,
            sts=clients.sts,
            k8s=clients.k8s,
            cluster_name=cluster,
        )
    except (AwsOperationError, K8sOperationError) as exc:
        err.print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR if isinstance(exc, AwsOperationError) else ExitCode.K8S_ERROR

    plan = generate(inventory, strategy=cast(Strategy, strategy), include_yellow=False)
    # Migrate is green-only: skip everything else even if generated as non-skip.
    for step in plan.steps:
        if step.risk != RiskClassification.GREEN:
            step.skip = True
            step.skip_reason = step.skip_reason or f"non-green ({step.risk.value})"

    writer = JournalWriter(journal or str(default_journal_path()))

    try:
        assoc_mod.preflight_addon(clients.eks, plan.cluster.name)
    except assoc_mod.PodIdentityAgentMissingError as exc:
        err.print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR

    # Phase: trust
    err.print(educational.apply_phase_intro(phase="trust"))
    console.print("[bold]phase=trust[/bold]")
    trust_result = run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(clients.iam),
        dry_run=False,
        continue_on_error=continue_on_error,
    )
    if trust_result.failed and not continue_on_error:
        return trust_result.exit_code()

    # Phase: association
    err.print(educational.apply_phase_intro(phase="association"))
    console.print("[bold]phase=association[/bold]")
    assoc_result = run_phase(
        plan,
        journal=writer,
        handler=assoc_mod.make_handler(clients.eks, plan),
        dry_run=False,
        continue_on_error=continue_on_error,
    )
    if assoc_result.failed and not continue_on_error:
        return assoc_result.exit_code()

    # Verify gate (informational — humans should restart pods to pick up new creds).
    err.print(educational.verify_intro())
    console.print("[bold]verify[/bold]")
    v = verify(plan, k8s=clients.k8s, probe=False)
    console.print(render_verify_summary(v))

    # Phase: cleanup (only if all SAs verified or dual; skip otherwise unless --continue-on-error)
    if v.has_remaining_irsa() and not continue_on_error:
        console.print(
            "[yellow]some pods still on IRSA — restart pods then re-run "
            "`apply --phase cleanup`. Skipping cleanup.[/yellow]"
        )
        return ExitCode.OK if not (trust_result.failed or assoc_result.failed) else ExitCode.PARTIAL

    err.print(educational.apply_phase_intro(phase="cleanup"))
    console.print("[bold]phase=cleanup[/bold]")
    cleanup_result = run_phase(
        plan,
        journal=writer,
        handler=cleanup_mod.make_handler(clients.k8s),
        dry_run=False,
        continue_on_error=continue_on_error,
    )

    if any(r.failed for r in (trust_result, assoc_result, cleanup_result)):
        return ExitCode.PARTIAL
    return ExitCode.OK
