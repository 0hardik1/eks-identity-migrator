"""Apply phase: remove the IRSA annotation from each migrated SA (spec §7.4)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eks_identity_migrator.apply.runner import PreparedStep
from eks_identity_migrator.aws.iam import IamClient, role_name_from_arn
from eks_identity_migrator.k8s.client import IRSA_ANNOTATION, K8sClient
from eks_identity_migrator.policy.translator import _is_oidc_irsa_statement
from eks_identity_migrator.types.journal import JournalOp
from eks_identity_migrator.types.plan import PlanStep


def make_handler(
    k8s: K8sClient,
    iam: IamClient | None = None,
    *,
    remove_oidc_trust: bool = False,
) -> Callable[[PlanStep], PreparedStep]:
    def handle(step: PlanStep) -> PreparedStep:
        sa_namespace = step.sa.namespace
        sa_name = step.sa.name
        prior_value = step.role_arn
        before: dict[str, object] = {"key": IRSA_ANNOTATION, "value": prior_value}
        after: dict[str, object] = {"key": IRSA_ANNOTATION, "value": None}

        # Maybe also strip OIDC trust statements from the role.
        oidc_trust_action: dict[str, object] | None = None
        if remove_oidc_trust and iam is not None:
            role = iam.get_role(step.role_arn)
            if role is not None:
                stripped = {
                    "Version": role.trust_policy.get("Version", "2012-10-17"),
                    "Statement": [
                        s
                        for s in (role.trust_policy.get("Statement") or [])
                        if isinstance(s, dict) and not _is_oidc_irsa_statement(s)
                    ],
                }
                before["roleTrustBefore"] = role.trust_policy
                after["roleTrustAfter"] = stripped
                oidc_trust_action = {"role_arn": step.role_arn, "stripped": stripped}

        def do() -> None:
            k8s.patch_service_account_annotations(sa_namespace, sa_name, {IRSA_ANNOTATION: None})
            if oidc_trust_action and iam is not None:
                stripped_doc: dict[str, Any] = oidc_trust_action["stripped"]  # type: ignore[assignment]
                iam.update_assume_role_policy(
                    role_name_from_arn(str(oidc_trust_action["role_arn"])),
                    stripped_doc,
                )

        return PreparedStep(
            op=JournalOp.K8S_REMOVE_SA_ANNOTATION,
            before=before,
            after=after,
            apply=do,
        )

    return handle
