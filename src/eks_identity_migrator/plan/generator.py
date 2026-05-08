"""Plan generator (spec §4 + §7.3 + §7.4).

Turns an Inventory into a Plan. Filters by --include-yellow flag (default:
green only). Red rows are always emitted but with `skip=true`.
Strategy-dependent rules (replace + multi-cluster → red) are applied here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from eks_identity_migrator.policy.translator import Strategy, translate
from eks_identity_migrator.risk.codes import FindingCode
from eks_identity_migrator.types.inventory import Inventory, Mapping, RiskClassification
from eks_identity_migrator.types.plan import (
    AnnotationCleanup,
    AssociationSpec,
    Plan,
    PlanStep,
)


def _should_force_red_for_replace(mapping: Mapping) -> bool:
    """Promote yellow → red when --strategy replace is unsafe.

    Replace is unsafe for multi-cluster role reuse (would strip other clusters'
    OIDC trust). EC2 mixed principals are still OK because the translator
    preserves them.
    """
    promote_codes = {FindingCode.ROLE_USED_BY_MULTIPLE_CLUSTERS.value}
    return any(f.code in promote_codes for f in mapping.findings)


def generate(
    inventory: Inventory,
    *,
    strategy: Strategy = "append",
    include_yellow: bool = False,
) -> Plan:
    cluster = inventory.cluster
    steps: list[PlanStep] = []
    for mapping in inventory.mappings:
        risk = mapping.risk
        skip = False
        skip_reason: str | None = None

        if strategy == "replace" and _should_force_red_for_replace(mapping):
            risk = RiskClassification.RED
            skip = True
            skip_reason = FindingCode.ROLE_USED_BY_MULTIPLE_CLUSTERS.value

        if risk == RiskClassification.RED:
            skip = True
            skip_reason = skip_reason or _first_red_code(mapping) or "RED"
        elif risk == RiskClassification.GRAY:
            skip = True
            skip_reason = skip_reason or _first_gray_code(mapping) or "GRAY"
        elif risk == RiskClassification.YELLOW and not include_yellow:
            skip = True
            skip_reason = "YELLOW (use --include-yellow to migrate)"

        # Translate even for skipped rows so the plan shows the intended diff.
        try:
            after = translate(
                mapping.trust_policy or {"Version": "2012-10-17", "Statement": []},
                strategy=strategy,
                cluster_arn=cluster.arn,
                account=cluster.account,
                sa_name=mapping.sa.name,
            )
        except Exception:
            after = mapping.trust_policy

        steps.append(
            PlanStep(
                sa=mapping.sa,
                role_arn=mapping.role_arn,
                risk=risk,
                skip=skip,
                skip_reason=skip_reason,
                trust_policy_before=mapping.trust_policy,
                trust_policy_after=after,
                association_create=AssociationSpec(
                    cluster_name=cluster.name,
                    namespace=mapping.sa.namespace,
                    service_account=mapping.sa.name,
                    role_arn=mapping.role_arn,
                ),
                annotation_cleanup=AnnotationCleanup(
                    namespace=mapping.sa.namespace,
                    service_account=mapping.sa.name,
                ),
                findings=list(mapping.findings),
            )
        )

    return Plan(
        cluster=cluster,
        strategy=strategy,
        generated_at=datetime.now(UTC),
        steps=steps,
    )


def _first_red_code(mapping: Mapping) -> str | None:
    for f in mapping.findings:
        if f.severity == "error":
            return f.code
    return None


def _first_gray_code(mapping: Mapping) -> str | None:
    for f in mapping.findings:
        if f.code in {
            FindingCode.STALE_ANNOTATION.value,
            FindingCode.ROLE_NOT_FOUND.value,
            FindingCode.POLICY_PARSE_ERROR.value,
        }:
            return f.code
    return None
