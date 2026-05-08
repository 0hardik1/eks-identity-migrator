"""EKS client Protocol + boto3 implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from eks_identity_migrator.aws.errors import wrap_client_error
from eks_identity_migrator.aws.session import make_config

if TYPE_CHECKING:
    from boto3.session import Session

POD_IDENTITY_ADDON_NAME = "eks-pod-identity-agent"


@dataclass(frozen=True)
class ClusterInfo:
    name: str
    arn: str
    region: str
    account: str
    oidc_issuer: str  # full URL form, e.g. "https://oidc.eks.us-west-2.amazonaws.com/id/EX"


@dataclass(frozen=True)
class PodIdentityAssociation:
    association_id: str
    association_arn: str
    cluster_name: str
    namespace: str
    service_account: str
    role_arn: str


@runtime_checkable
class EksClient(Protocol):
    def describe_cluster(self, name: str) -> ClusterInfo: ...

    def list_addons(self, cluster_name: str) -> list[str]: ...

    def list_pod_identity_associations(
        self, cluster_name: str, namespace: str | None = None, service_account: str | None = None
    ) -> list[PodIdentityAssociation]: ...

    def create_pod_identity_association(
        self, *, cluster_name: str, namespace: str, service_account: str, role_arn: str
    ) -> PodIdentityAssociation: ...

    def delete_pod_identity_association(self, cluster_name: str, association_id: str) -> None: ...


class BotoEksClient:
    def __init__(self, session: Session, *, endpoint_url: str | None = None) -> None:
        self._client = session.client("eks", config=make_config(), endpoint_url=endpoint_url)

    def describe_cluster(self, name: str) -> ClusterInfo:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.describe_cluster(name=name)
        except ClientError as exc:
            raise wrap_client_error("eks:DescribeCluster", exc) from exc
        cluster = resp["cluster"]
        arn = cluster["arn"]
        # arn: arn:aws:eks:<region>:<account>:cluster/<name>
        parts = arn.split(":")
        region = parts[3] if len(parts) > 3 else ""
        account = parts[4] if len(parts) > 4 else ""
        issuer = ((cluster.get("identity") or {}).get("oidc") or {}).get("issuer", "")
        return ClusterInfo(
            name=cluster["name"],
            arn=arn,
            region=region,
            account=account,
            oidc_issuer=issuer,
        )

    def list_addons(self, cluster_name: str) -> list[str]:
        from botocore.exceptions import ClientError

        try:
            paginator = self._client.get_paginator("list_addons")
            names: list[str] = []
            for page in paginator.paginate(clusterName=cluster_name):
                names.extend(page.get("addons", []))
            return names
        except ClientError as exc:
            raise wrap_client_error("eks:ListAddons", exc) from exc

    def list_pod_identity_associations(
        self, cluster_name: str, namespace: str | None = None, service_account: str | None = None
    ) -> list[PodIdentityAssociation]:
        from botocore.exceptions import ClientError

        try:
            kwargs: dict[str, Any] = {"clusterName": cluster_name}
            if namespace:
                kwargs["namespace"] = namespace
            if service_account:
                kwargs["serviceAccount"] = service_account
            paginator = self._client.get_paginator("list_pod_identity_associations")
            assocs: list[PodIdentityAssociation] = []
            for page in paginator.paginate(**kwargs):
                for a in page.get("associations", []):
                    # The list operation returns sparse fields; describe to fill in role_arn.
                    desc = self._client.describe_pod_identity_association(
                        clusterName=cluster_name, associationId=a["associationId"]
                    )["association"]
                    assocs.append(
                        PodIdentityAssociation(
                            association_id=desc["associationId"],
                            association_arn=desc.get("associationArn", ""),
                            cluster_name=cluster_name,
                            namespace=desc.get("namespace", ""),
                            service_account=desc.get("serviceAccount", ""),
                            role_arn=desc.get("roleArn", ""),
                        )
                    )
            return assocs
        except ClientError as exc:
            raise wrap_client_error(
                "eks:ListPodIdentityAssociations",
                exc,
                sa=f"{namespace}/{service_account}" if namespace and service_account else None,
            ) from exc

    def create_pod_identity_association(
        self, *, cluster_name: str, namespace: str, service_account: str, role_arn: str
    ) -> PodIdentityAssociation:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.create_pod_identity_association(
                clusterName=cluster_name,
                namespace=namespace,
                serviceAccount=service_account,
                roleArn=role_arn,
            )
        except ClientError as exc:
            raise wrap_client_error(
                "eks:CreatePodIdentityAssociation",
                exc,
                sa=f"{namespace}/{service_account}",
                role_arn=role_arn,
            ) from exc
        a = resp["association"]
        return PodIdentityAssociation(
            association_id=a["associationId"],
            association_arn=a.get("associationArn", ""),
            cluster_name=cluster_name,
            namespace=namespace,
            service_account=service_account,
            role_arn=role_arn,
        )

    def delete_pod_identity_association(self, cluster_name: str, association_id: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.delete_pod_identity_association(
                clusterName=cluster_name, associationId=association_id
            )
        except ClientError as exc:
            raise wrap_client_error("eks:DeletePodIdentityAssociation", exc) from exc
