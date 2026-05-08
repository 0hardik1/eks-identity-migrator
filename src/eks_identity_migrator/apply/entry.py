"""Wire `apply --phase ...` to the actual phase handlers."""

from __future__ import annotations

from rich.console import Console

from eks_identity_migrator.apply.runner import run_phase
from eks_identity_migrator.aws.eks import BotoEksClient
from eks_identity_migrator.aws.iam import BotoIamClient
from eks_identity_migrator.aws.session import make_session
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.journal.writer import JournalWriter, default_journal_path
from eks_identity_migrator.k8s.client import KubernetesClient
from eks_identity_migrator.k8s.config import load_kube_config
from eks_identity_migrator.plan.io import read_plan


def run(
    *,
    plan: str,
    phase: str,
    dry_run: bool,
    continue_on_error: bool,
    journal: str | None,
    remove_oidc_trust: bool,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.apply import association as assoc_mod
    from eks_identity_migrator.apply import cleanup as cleanup_mod
    from eks_identity_migrator.apply import trust as trust_mod
    from eks_identity_migrator.aws.errors import AwsOperationError
    from eks_identity_migrator.k8s.errors import K8sOperationError

    console = Console()

    if phase not in {"trust", "association", "cleanup"}:
        Console(stderr=True).print(
            "[red]error:[/red] --phase must be one of trust|association|cleanup"
        )
        return ExitCode.INVALID_INPUT

    try:
        plan_obj = read_plan(plan)
    except Exception as exc:
        Console(stderr=True).print(f"[red]error:[/red] failed to load plan: {exc}")
        return ExitCode.INVALID_INPUT

    journal_path = journal or str(default_journal_path())
    writer = JournalWriter(journal_path)

    session = make_session(region=region, profile=profile)

    try:
        if phase == "trust":
            iam = BotoIamClient(session)
            handler = trust_mod.make_handler(iam)
        elif phase == "association":
            eks = BotoEksClient(session)
            assoc_mod.preflight_addon(eks, plan_obj.cluster.name)
            handler = assoc_mod.make_handler(eks, plan_obj)
        else:  # cleanup
            load_kube_config()
            k8s = KubernetesClient()
            iam_for_cleanup: BotoIamClient | None = (
                BotoIamClient(session) if remove_oidc_trust else None
            )
            handler = cleanup_mod.make_handler(
                k8s, iam=iam_for_cleanup, remove_oidc_trust=remove_oidc_trust
            )
    except assoc_mod.PodIdentityAgentMissingError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR
    except AwsOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.AWS_ERROR
    except K8sOperationError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        return ExitCode.K8S_ERROR

    result = run_phase(
        plan_obj,
        journal=writer,
        handler=handler,
        dry_run=dry_run,
        continue_on_error=continue_on_error,
    )
    label = f"phase={phase}{' [dry-run]' if dry_run else ''}"
    console.print(
        f"{label}: {result.succeeded} succeeded, {result.skipped} skipped, "
        f"{result.failed} failed (journal: {journal_path})"
    )
    if result.errors:
        for err in result.errors:
            console.print(f"  [red]✗[/red] {err}")
    return result.exit_code()
