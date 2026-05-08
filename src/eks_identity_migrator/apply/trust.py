"""Apply phase: update IAM trust policies (spec §7.4)."""

from __future__ import annotations

from collections.abc import Callable

from eks_identity_migrator.apply.runner import PreparedStep
from eks_identity_migrator.aws.iam import IamClient, role_name_from_arn
from eks_identity_migrator.policy.canonicalizer import policies_equivalent
from eks_identity_migrator.types.journal import JournalOp
from eks_identity_migrator.types.plan import PlanStep


def make_handler(iam: IamClient) -> Callable[[PlanStep], PreparedStep]:
    def handle(step: PlanStep) -> PreparedStep:
        role = iam.get_role(step.role_arn)
        if role is None:
            return PreparedStep(
                op=JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
                before={},
                after={},
                error=f"role {step.role_arn} not found",
            )
        before = role.trust_policy
        target = step.trust_policy_after
        if policies_equivalent(before, target):
            return PreparedStep(
                op=JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
                before=before,
                after=before,
                note="already-applied",
            )

        def do() -> None:
            iam.update_assume_role_policy(role_name_from_arn(step.role_arn), target)

        return PreparedStep(
            op=JournalOp.IAM_UPDATE_ASSUME_ROLE_POLICY,
            before=before,
            after=target,
            apply=do,
        )

    return handle
