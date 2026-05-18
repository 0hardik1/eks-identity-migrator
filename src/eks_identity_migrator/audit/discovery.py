"""Discovery orchestration (spec §7.1).

Joins AWS (cluster info, IAM roles) and K8s (ServiceAccounts, pods) reads
into a single :class:`Inventory`. Designed to be readable: each step in
:func:`discover` corresponds to one bullet in the spec.
"""

from __future__ import annotations

from eks_identity_migrator.audit.joiner import join
from eks_identity_migrator.aws.eks import EksClient
from eks_identity_migrator.aws.iam import IamClient, IamRole
from eks_identity_migrator.aws.sts import StsClient
from eks_identity_migrator.k8s.client import IRSA_ANNOTATION, K8sClient
from eks_identity_migrator.types.inventory import ClusterRef, Inventory


def discover(
    *,
    eks: EksClient,
    iam: IamClient,
    sts: StsClient,
    k8s: K8sClient,
    cluster_name: str,
    namespace: str | None = None,
    service_account: str | None = None,
) -> Inventory:
    """Full discovery: cluster info → SAs → pods → roles → joined Inventory."""
    info = eks.describe_cluster(cluster_name)
    account = info.account
    if not account:
        # DescribeCluster usually returns the ARN with the account ID, but some
        # IAM-tightened setups don't. STS:GetCallerIdentity is the safe fallback
        # because we already need STS permissions for the rest of the audit.
        account = sts.get_caller_identity().account
    cluster = ClusterRef(
        name=info.name,
        region=info.region,
        account=account,
        oidc_issuer=info.oidc_issuer,
        arn=info.arn,
    )

    sas = k8s.list_service_accounts(namespace=namespace)
    if service_account:
        sas = [sa for sa in sas if sa.name == service_account and sa.namespace == namespace]

    # An SA is only "in scope" for migration if it carries the IRSA annotation;
    # unannotated SAs don't bind to an IAM role and have nothing to migrate.
    annotated = [sa for sa in sas if IRSA_ANNOTATION in sa.annotations]

    # Pod listing is scoped to namespaces that contain annotated SAs. We need
    # cross-namespace coverage because a pod can mount a default SA *and* an
    # annotated SA from the same namespace — the table shows which pods use what,
    # so missing namespaces would hide real usage.
    namespaces = {sa.namespace for sa in annotated}
    if namespace and not namespaces:
        namespaces = {namespace}

    pods = []
    for ns in sorted(namespaces):
        pods.extend(k8s.list_pods(namespace=ns))

    # Roles are cached per ARN: many SAs reuse the same role, and
    # GetRole is the slowest call per SA. A simple dict avoids N+1 lookups.
    role_lookup: dict[str, IamRole | None] = {}
    for sa in annotated:
        arn = sa.annotations[IRSA_ANNOTATION]
        if arn not in role_lookup:
            role_lookup[arn] = iam.get_role(arn)

    return join(cluster, annotated, pods, role_lookup)
