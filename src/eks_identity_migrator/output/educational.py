"""Short, terminal-rendered explanations the CLI prints around real output.

The goal is that a first-time user can run the tool and *learn* what IRSA is,
what Pod Identity is, and what each phase actually changes — without having to
open the spec. Each renderer returns a Rich ``Group`` that the caller prints
to **stderr** (so ``--out`` and pipe-to-jq workflows aren't polluted).

The global ``--quiet`` flag is read here via a module-level toggle set by
``cli/__init__.py``. Tests reset it with ``set_quiet(False)``.

Editing one of these is safe: change the text, run ``pytest
tests/output/test_educational.py``, and the assertions will tell you if a
required teaching phrase is missing.
"""

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

_quiet: bool = False


def set_quiet(quiet: bool) -> None:
    """Toggle the module-wide quiet flag — set by the root CLI callback."""
    global _quiet
    _quiet = quiet


def _empty() -> Group:
    return Group()


def _panel(title: str, body: str) -> Group:
    return Group(
        Panel(
            Text.from_markup(body.strip("\n")),
            title=title,
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        )
    )


# ---- audit ----------------------------------------------------------------


def audit_intro() -> Group:
    if _quiet:
        return _empty()
    return _panel(
        "audit — what IRSA is, what we're about to do",
        "[bold]IRSA[/bold] (IAM Roles for Service Accounts) maps a Kubernetes\n"
        "ServiceAccount to an AWS IAM role over [bold]OIDC[/bold]. Each annotated\n"
        "SA has [cyan]eks.amazonaws.com/role-arn[/cyan] set to a role ARN.\n"
        "\n"
        "We enumerate every annotated SA, find pods using it, and classify\n"
        "each role's trust policy for migration safety to [bold]Pod Identity[/bold].",
    )


def audit_outro() -> Group:
    if _quiet:
        return _empty()
    return _panel(
        "what the risk colours mean — next steps",
        "[green]green[/green]   safe to auto-migrate to Pod Identity\n"
        "[yellow]yellow[/yellow]  migratable with review (operator SA, multi-statement trust)\n"
        "[red]red[/red]     requires human decision (cross-account, custom OIDC claims)\n"
        "[bright_black]gray[/bright_black]    insufficient info (role not found, parse error)\n"
        "\n"
        "Next: run [cyan]eks-identity-migrator plan[/cyan] to generate "
        "[cyan]plan.yaml[/cyan] for the green rows.",
    )


# ---- plan -----------------------------------------------------------------


def plan_intro(*, strategy: str) -> Group:
    if _quiet:
        return _empty()
    if strategy == "replace":
        strategy_note = (
            "[bold]Strategy=replace[/bold]: we will [red]strip[/red] the OIDC trust\n"
            "statements. Use this only when no other cluster shares the role."
        )
    else:
        strategy_note = (
            "[bold]Strategy=append[/bold]: we keep OIDC trust statements intact and\n"
            "[green]add[/green] a Pod Identity statement next to them — safe if the\n"
            "role is shared across clusters."
        )
    return _panel(
        "plan — a reviewable YAML before any AWS write",
        "Migration runs in three phases:\n"
        "  1. [bold]trust[/bold]       update each IAM role's trust policy\n"
        "  2. [bold]association[/bold] create the EKS Pod Identity Association\n"
        "  3. [bold]cleanup[/bold]     remove the legacy IRSA annotation\n"
        "\n" + strategy_note,
    )


# ---- apply ----------------------------------------------------------------


_PHASE_BODIES: dict[str, str] = {
    "trust": (
        "[bold]Phase 1 of 3 — trust[/bold]\n"
        "We update each IAM role's [bold]trust policy[/bold] so it can be assumed\n"
        "by [cyan]pods.eks.amazonaws.com[/cyan]. With [bold]--strategy append[/bold]\n"
        "the existing OIDC statements stay in place; pods keep working via IRSA\n"
        "until we cut over.\n"
        "\n"
        "Every write is recorded in the [bold]journal[/bold] — reversible via\n"
        "[cyan]rollback --phase trust[/cyan]."
    ),
    "association": (
        "[bold]Phase 2 of 3 — association[/bold]\n"
        "We create an EKS [bold]Pod Identity Association[/bold] (cluster ↔ ns/SA\n"
        "↔ role). New pods that mount the SA pick up the Pod Identity credentials\n"
        "automatically; you must restart existing pods for them to see it.\n"
        "\n"
        "Reversible from the journal."
    ),
    "cleanup": (
        "[bold]Phase 3 of 3 — cleanup[/bold]\n"
        "We remove the legacy IRSA [bold]annotation[/bold] from each ServiceAccount\n"
        "(and, with [bold]--remove-oidc-trust[/bold], drop the OIDC statement from\n"
        "the role's trust policy). Only run this after [cyan]verify[/cyan] confirms\n"
        "every pod is on Pod Identity.\n"
        "\n"
        "Reversible from the journal."
    ),
}


def apply_phase_intro(*, phase: str) -> Group:
    if _quiet:
        return _empty()
    body = _PHASE_BODIES.get(phase)
    if not body:
        return _empty()
    return _panel(f"apply — phase={phase}", body)


# ---- verify ---------------------------------------------------------------


def verify_intro() -> Group:
    if _quiet:
        return _empty()
    return _panel(
        "verify — which credential source is each pod using?",
        "IRSA pods have [cyan]AWS_WEB_IDENTITY_TOKEN_FILE[/cyan] in their env.\n"
        "Pod Identity pods have [cyan]AWS_CONTAINER_CREDENTIALS_FULL_URI[/cyan].\n"
        "Both present ⇒ the SDK will pick Pod Identity first; restart the pod\n"
        "to drop the legacy IRSA env once you're confident.\n"
        "\n"
        "[bold]--probe[/bold] runs [cyan]sts:GetCallerIdentity[/cyan] inside the pod\n"
        "to confirm the role assumption end-to-end.",
    )


# ---- rollback -------------------------------------------------------------


def rollback_intro() -> Group:
    if _quiet:
        return _empty()
    return _panel(
        "rollback — replay the journal in reverse",
        "Every apply mutation is recorded as an NDJSON entry in the [bold]journal[/bold]\n"
        "([cyan].eks-identity-migrator/journal-<ts>.json[/cyan]). Rollback walks the\n"
        "journal in reverse and inverts each successful operation:\n"
        "  - trust       → restore the previous trust policy JSON\n"
        "  - association → delete the Pod Identity Association\n"
        "  - cleanup     → re-add the IRSA annotation",
    )


# ---- migrate --------------------------------------------------------------


def migrate_intro() -> Group:
    if _quiet:
        return _empty()
    return _panel(
        "migrate — green-only fast path",
        "Runs [bold]audit → plan → apply trust → apply association → verify → cleanup[/bold]\n"
        "in one shot, but only for [green]green[/green]-classified SAs. Anything\n"
        "[yellow]yellow[/yellow] or [red]red[/red] is skipped — you'll handle those\n"
        "manually via the staged subcommands.\n"
        "\n"
        "Cleanup is gated on every pod showing as Pod Identity in verify.",
    )
