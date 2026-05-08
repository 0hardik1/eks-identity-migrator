"""`migrate` convenience: green-only end-to-end with verification gates."""

from __future__ import annotations

from typing import cast

from rich.console import Console

from eks_identity_migrator.apply import association as assoc_mod
from eks_identity_migrator.apply import cleanup as cleanup_mod
from eks_identity_migrator.apply import trust as trust_mod
from eks_identity_migrator.apply.runner import run_phase
from eks_identity_migrator.audit.discovery import discover
from eks_identity_migrator.aws.eks import BotoEksClient
from eks_identity_migrator.aws.iam import BotoIamClient
from eks_identity_migrator.aws.session import make_session
from eks_identity_migrator.aws.sts import BotoStsClient
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.journal.writer import JournalWriter, default_journal_path
from eks_identity_migrator.k8s.client import KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config
from eks_identity_migrator.plan.generator import generate
from eks_identity_migrator.policy.translator import Strategy
from eks_identity_migrator.types.inventory import RiskClassification
from eks_identity_migrator.verify.probe import verify


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
    if strategy not in {"append", "replace"}:
        Console(stderr=True).print("[red]error:[/red] --strategy must be 'append' or 'replace'")
        return ExitCode.INVALID_INPUT

    session = make_session(region=region, profile=profile)
    iam = BotoIamClient(session)
    eks = BotoEksClient(session)
    sts = BotoStsClient(session)
    load_kube_config()
    k8s = KubernetesClient()

    try:
        inventory = discover(eks=eks, iam=iam, sts=sts, k8s=k8s, cluster_name=cluster)
    except (AwsOperationError, K8sOperationError) as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR if isinstance(exc, AwsOperationError) else ExitCode.K8S_ERROR

    plan = generate(inventory, strategy=cast(Strategy, strategy), include_yellow=False)
    # Migrate is green-only: skip everything else even if generated as non-skip.
    for step in plan.steps:
        if step.risk != RiskClassification.GREEN:
            step.skip = True
            step.skip_reason = step.skip_reason or f"non-green ({step.risk.value})"

    journal_path = journal or str(default_journal_path())
    writer = JournalWriter(journal_path)

    try:
        assoc_mod.preflight_addon(eks, plan.cluster.name)
    except assoc_mod.PodIdentityAgentMissingError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR

    # Phase: trust
    console.print("[bold]phase=trust[/bold]")
    trust_result = run_phase(
        plan,
        journal=writer,
        handler=trust_mod.make_handler(iam),
        dry_run=False,
        continue_on_error=continue_on_error,
    )
    if trust_result.failed and not continue_on_error:
        return trust_result.exit_code()

    # Phase: association
    console.print("[bold]phase=association[/bold]")
    assoc_result = run_phase(
        plan,
        journal=writer,
        handler=assoc_mod.make_handler(eks, plan),
        dry_run=False,
        continue_on_error=continue_on_error,
    )
    if assoc_result.failed and not continue_on_error:
        return assoc_result.exit_code()

    # Verify gate (informational — humans should restart pods to pick up new creds).
    console.print("[bold]verify[/bold]")
    v = verify(plan, k8s=k8s, probe=False)
    from eks_identity_migrator.verify.probe import render_verify_summary

    console.print(render_verify_summary(v))

    # Phase: cleanup (only if all SAs verified or dual; skip otherwise unless --continue-on-error)
    if v.has_remaining_irsa() and not continue_on_error:
        console.print(
            "[yellow]some pods still on IRSA — restart pods then re-run "
            "`apply --phase cleanup`. Skipping cleanup.[/yellow]"
        )
        return ExitCode.OK if not (trust_result.failed or assoc_result.failed) else ExitCode.PARTIAL

    console.print("[bold]phase=cleanup[/bold]")
    cleanup_result = run_phase(
        plan,
        journal=writer,
        handler=cleanup_mod.make_handler(k8s),
        dry_run=False,
        continue_on_error=continue_on_error,
    )

    if any(r.failed for r in (trust_result, assoc_result, cleanup_result)):
        return ExitCode.PARTIAL
    return ExitCode.OK
