"""Discovery orchestration (spec §7.1)."""

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
        # Fall back to STS if EKS didn't include it in the ARN parsing.
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

    annotated = [sa for sa in sas if IRSA_ANNOTATION in sa.annotations]

    # Pods only need to be listed in namespaces that have annotated SAs (and the
    # caller's namespace filter, if any). For correctness with default-SA usage,
    # we list pods in every namespace that has at least one annotated SA.
    namespaces = {sa.namespace for sa in annotated}
    if namespace and not namespaces:
        namespaces = {namespace}

    pods = []
    for ns in sorted(namespaces):
        pods.extend(k8s.list_pods(namespace=ns))

    role_lookup: dict[str, IamRole | None] = {}
    for sa in annotated:
        arn = sa.annotations[IRSA_ANNOTATION]
        if arn not in role_lookup:
            role_lookup[arn] = iam.get_role(arn)

    return join(cluster, annotated, pods, role_lookup)
