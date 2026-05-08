"""Join K8s + IAM data into Mappings (spec §7.1 step 5+)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC

from eks_identity_migrator.aws.iam import IamRole
from eks_identity_migrator.k8s.client import IRSA_ANNOTATION, PodInfo, ServiceAccountRef
from eks_identity_migrator.risk import MappingContext, PodEnvVar, classify
from eks_identity_migrator.risk.codes import FindingCode
from eks_identity_migrator.types.inventory import (
    ClusterRef,
    FindingModel,
    Inventory,
    Mapping,
    PodRef,
    RiskClassification,
    SARef,
)


def _pod_envs_for_sa(pods: list[PodInfo]) -> tuple[PodEnvVar, ...]:
    """Aggregate env vars from the first container of each pod."""
    aggregated: dict[str, PodEnvVar] = {}
    for pod in pods:
        for _container, envs in pod.container_envs.items():
            for name, value, value_from_kind in envs:
                if name not in aggregated:
                    aggregated[name] = PodEnvVar(
                        name=name, value=value, value_from_kind=value_from_kind
                    )
    return tuple(aggregated.values())


def _pod_refs(pods: list[PodInfo]) -> list[PodRef]:
    return [PodRef(namespace=p.namespace, name=p.name, owner=p.owner) for p in pods]


def join(
    cluster: ClusterRef,
    sas: Iterable[ServiceAccountRef],
    pods: Iterable[PodInfo],
    role_lookup: dict[str, IamRole | None],
) -> Inventory:
    """Build an Inventory from cluster + SA list + pod list + role lookup.

    `role_lookup` maps role ARN → IamRole or None (None means IAM said
    `NoSuchEntity` — we still emit a Mapping with a `ROLE_NOT_FOUND` finding).
    """
    sa_list = list(sas)
    pod_list = list(pods)

    # Index pods by (ns, sa). Default-SA expansion happened at the K8s client.
    pods_by_key: dict[tuple[str, str], list[PodInfo]] = defaultdict(list)
    for pod in pod_list:
        pods_by_key[(pod.namespace, pod.service_account)].append(pod)

    mappings: list[Mapping] = []
    stale_annotations: list[SARef] = []
    annotated_role_arns: set[str] = set()

    for sa in sa_list:
        role_arn = sa.annotations.get(IRSA_ANNOTATION)
        if not role_arn:
            continue
        annotated_role_arns.add(role_arn)
        sa_ref = SARef(namespace=sa.namespace, name=sa.name)
        used_pods = pods_by_key.get((sa.namespace, sa.name), [])

        # Resolve the role (or surface ROLE_NOT_FOUND).
        role = role_lookup.get(role_arn)
        extra_findings: list[FindingModel] = []
        permission_boundary: str | None = None
        if role is None:
            # We don't have a parsed trust policy — emit a synthetic gray finding.
            # Skip the classifier (no parsed policy) and produce a gray Mapping.
            mappings.append(
                Mapping(
                    sa=sa_ref,
                    role_arn=role_arn,
                    trust_policy={},
                    used_by_pods=_pod_refs(used_pods),
                    risk=RiskClassification.GRAY,
                    findings=[
                        FindingModel(
                            code=FindingCode.ROLE_NOT_FOUND.value,
                            severity="error",
                            message=f"IAM role {role_arn} does not exist (or is not accessible).",
                            hint="Remove the SA annotation if the role was deleted.",
                        )
                    ],
                )
            )
            if not used_pods:
                stale_annotations.append(sa_ref)
            continue

        permission_boundary = role.permission_boundary
        if not used_pods:
            stale_annotations.append(sa_ref)

        from eks_identity_migrator.policy.parser import try_parse_trust_policy

        parsed = try_parse_trust_policy(role.trust_policy)
        ctx = MappingContext(
            cluster_name=cluster.name,
            cluster_arn=cluster.arn,
            cluster_account=cluster.account,
            cluster_oidc_issuer=cluster.oidc_issuer,
            sa_namespace=sa.namespace,
            sa_name=sa.name,
            role_account=_role_account_from_arn(role_arn),
            permission_boundary=permission_boundary,
            pod_envs=_pod_envs_for_sa(used_pods),
            used_by_pods_count=len(used_pods),
        )
        risk, findings = classify(parsed, ctx, extra_findings=extra_findings)
        mappings.append(
            Mapping(
                sa=sa_ref,
                role_arn=role_arn,
                trust_policy=role.trust_policy,
                permission_boundary=permission_boundary,
                used_by_pods=_pod_refs(used_pods),
                risk=risk,
                findings=findings,
            )
        )

    # Mappings are unique-by-SA (namespace, name).
    mappings.sort(key=lambda m: (m.sa.namespace, m.sa.name))
    stale_annotations.sort(key=lambda s: (s.namespace, s.name))

    from datetime import datetime

    return Inventory(
        cluster=cluster,
        generated_at=datetime.now(UTC),
        mappings=mappings,
        orphan_roles=[],  # populated by audit caller if it wants to scan all roles
        stale_annotations=stale_annotations,
    )


def _role_account_from_arn(arn: str) -> str | None:
    parts = arn.split(":")
    if len(parts) >= 5 and parts[4]:
        return parts[4]
    return None
