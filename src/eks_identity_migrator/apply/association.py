"""Apply phase: create EKS Pod Identity Associations (spec §7.4 + gotcha 10)."""

from __future__ import annotations

from collections.abc import Callable

from eks_identity_migrator.apply.runner import PreparedStep
from eks_identity_migrator.aws.eks import POD_IDENTITY_ADDON_NAME, EksClient
from eks_identity_migrator.types.journal import JournalOp
from eks_identity_migrator.types.plan import Plan, PlanStep


class PodIdentityAgentMissingError(RuntimeError):
    """Raised before the phase runs if the addon isn't present (gotcha 10)."""


def preflight_addon(eks: EksClient, cluster_name: str) -> None:
    addons = eks.list_addons(cluster_name)
    if POD_IDENTITY_ADDON_NAME not in addons:
        raise PodIdentityAgentMissingError(
            f"EKS addon {POD_IDENTITY_ADDON_NAME!r} is not installed on cluster {cluster_name!r}. "
            "Install it before running `apply --phase association`."
        )


def make_handler(eks: EksClient, plan: Plan) -> Callable[[PlanStep], PreparedStep]:
    cluster = plan.cluster.name

    def handle(step: PlanStep) -> PreparedStep:
        existing = eks.list_pod_identity_associations(
            cluster, namespace=step.sa.namespace, service_account=step.sa.name
        )
        if existing:
            for a in existing:
                if a.role_arn == step.role_arn:
                    return PreparedStep(
                        op=JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION,
                        before={"associationId": a.association_id},
                        after={"associationId": a.association_id},
                        note="already-applied",
                    )
            other = existing[0]
            return PreparedStep(
                op=JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION,
                before={"existingRoleArn": other.role_arn},
                after={},
                error=(
                    f"existing Pod Identity Association {other.association_id} for "
                    f"{step.sa} points to {other.role_arn}, expected {step.role_arn}"
                ),
            )

        # Capture state for the closure.
        ns = step.sa.namespace
        sa = step.sa.name
        role_arn = step.role_arn
        # Holder so success path can write the new assoc id into `after`.
        holder: dict[str, object] = {}

        def do() -> None:
            created = eks.create_pod_identity_association(
                cluster_name=cluster, namespace=ns, service_account=sa, role_arn=role_arn
            )
            holder["associationId"] = created.association_id
            holder["roleArn"] = created.role_arn

        return PreparedStep(
            op=JournalOp.EKS_CREATE_POD_IDENTITY_ASSOCIATION,
            before={},
            after=holder,
            apply=do,
        )

    return handle
