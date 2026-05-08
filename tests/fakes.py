"""In-memory fakes for the AWS + K8s Protocols.

Used by audit/plan/apply/verify/rollback tests to exercise the full code path
without spinning up real clients. Each fake is a Protocol-conformant object
with extra methods to seed state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from eks_identity_migrator.aws.eks import ClusterInfo, PodIdentityAssociation
from eks_identity_migrator.aws.iam import IamRole, role_name_from_arn
from eks_identity_migrator.aws.sts import CallerIdentity
from eks_identity_migrator.k8s.client import PodInfo, ServiceAccountRef

# ---------------------------------------------------------------- IAM


class FakeIamClient:
    def __init__(self) -> None:
        self.roles: dict[str, IamRole] = {}
        self.update_calls: list[tuple[str, dict[str, Any]]] = []

    def add_role(
        self,
        arn: str,
        trust_policy: dict[str, Any],
        *,
        permission_boundary: str | None = None,
    ) -> None:
        self.roles[arn] = IamRole(
            arn=arn,
            name=role_name_from_arn(arn),
            trust_policy=trust_policy,
            permission_boundary=permission_boundary,
        )

    def get_role(self, role_arn: str) -> IamRole | None:
        return self.roles.get(role_arn)

    def update_assume_role_policy(self, role_name: str, policy_document: dict[str, Any]) -> None:
        self.update_calls.append((role_name, policy_document))
        for arn, role in list(self.roles.items()):
            if role.name == role_name:
                self.roles[arn] = IamRole(
                    arn=role.arn,
                    name=role.name,
                    trust_policy=policy_document,
                    permission_boundary=role.permission_boundary,
                )
                return
        # Mirror IAM behaviour: missing role raises.
        raise RuntimeError(f"NoSuchEntity: {role_name}")


# ---------------------------------------------------------------- EKS


@dataclass
class FakeEksClient:
    clusters: dict[str, ClusterInfo] = field(default_factory=dict)
    addons: dict[str, list[str]] = field(default_factory=dict)
    associations: list[PodIdentityAssociation] = field(default_factory=list)
    create_calls: list[dict[str, Any]] = field(default_factory=list)
    delete_calls: list[str] = field(default_factory=list)

    def add_cluster(self, info: ClusterInfo, *, addons: list[str] | None = None) -> None:
        self.clusters[info.name] = info
        self.addons[info.name] = list(addons or [])

    def describe_cluster(self, name: str) -> ClusterInfo:
        if name not in self.clusters:
            raise RuntimeError(f"ResourceNotFoundException: cluster {name}")
        return self.clusters[name]

    def list_addons(self, cluster_name: str) -> list[str]:
        return list(self.addons.get(cluster_name, []))

    def list_pod_identity_associations(
        self,
        cluster_name: str,
        namespace: str | None = None,
        service_account: str | None = None,
    ) -> list[PodIdentityAssociation]:
        out = [a for a in self.associations if a.cluster_name == cluster_name]
        if namespace:
            out = [a for a in out if a.namespace == namespace]
        if service_account:
            out = [a for a in out if a.service_account == service_account]
        return out

    def create_pod_identity_association(
        self, *, cluster_name: str, namespace: str, service_account: str, role_arn: str
    ) -> PodIdentityAssociation:
        # Mirror EKS behaviour: refuse a duplicate (same cluster+ns+sa).
        for a in self.associations:
            if (
                a.cluster_name == cluster_name
                and a.namespace == namespace
                and a.service_account == service_account
            ):
                raise RuntimeError(
                    f"ResourceInUseException: association exists for {namespace}/{service_account}"
                )
        association_id = f"a-{uuid4().hex[:16]}"
        a = PodIdentityAssociation(
            association_id=association_id,
            association_arn=f"arn:aws:eks:us-west-2:000000000000:podidentityassociation/{cluster_name}/{association_id}",
            cluster_name=cluster_name,
            namespace=namespace,
            service_account=service_account,
            role_arn=role_arn,
        )
        self.associations.append(a)
        self.create_calls.append(
            {
                "clusterName": cluster_name,
                "namespace": namespace,
                "serviceAccount": service_account,
                "roleArn": role_arn,
            }
        )
        return a

    def delete_pod_identity_association(self, cluster_name: str, association_id: str) -> None:
        self.delete_calls.append(association_id)
        self.associations = [
            a
            for a in self.associations
            if not (a.cluster_name == cluster_name and a.association_id == association_id)
        ]


# ---------------------------------------------------------------- STS


@dataclass
class FakeStsClient:
    account: str = "123456789012"
    arn: str = "arn:aws:iam::123456789012:user/tester"
    user_id: str = "AIDAEXAMPLE"

    def get_caller_identity(self) -> CallerIdentity:
        return CallerIdentity(account=self.account, arn=self.arn, user_id=self.user_id)


# ---------------------------------------------------------------- K8s


@dataclass
class FakeK8sClient:
    service_accounts: list[ServiceAccountRef] = field(default_factory=list)
    pods: list[PodInfo] = field(default_factory=list)
    patch_calls: list[tuple[str, str, dict[str, str | None]]] = field(default_factory=list)
    exec_responses: dict[tuple[str, str], str] = field(default_factory=dict)

    def add_sa(
        self, namespace: str, name: str, *, annotations: dict[str, str] | None = None
    ) -> None:
        self.service_accounts.append(
            ServiceAccountRef(namespace=namespace, name=name, annotations=dict(annotations or {}))
        )

    def add_pod(
        self,
        namespace: str,
        name: str,
        *,
        sa: str | None = None,
        phase: str = "Running",
        owner: str = "",
        envs: dict[str, list[tuple[str, str | None, str | None]]] | None = None,
    ) -> None:
        self.pods.append(
            PodInfo(
                namespace=namespace,
                name=name,
                service_account=sa or "default",
                phase=phase,
                owner=owner,
                container_envs=envs or {},
            )
        )

    def list_service_accounts(self, namespace: str | None = None) -> list[ServiceAccountRef]:
        if namespace:
            return [s for s in self.service_accounts if s.namespace == namespace]
        return list(self.service_accounts)

    def list_pods(self, namespace: str | None = None) -> list[PodInfo]:
        if namespace:
            return [p for p in self.pods if p.namespace == namespace]
        return list(self.pods)

    def patch_service_account_annotations(
        self, namespace: str, name: str, annotations_patch: dict[str, str | None]
    ) -> None:
        self.patch_calls.append((namespace, name, dict(annotations_patch)))
        for i, sa in enumerate(self.service_accounts):
            if sa.namespace == namespace and sa.name == name:
                annos = dict(sa.annotations)
                for k, v in annotations_patch.items():
                    if v is None:
                        annos.pop(k, None)
                    else:
                        annos[k] = v
                self.service_accounts[i] = ServiceAccountRef(
                    namespace=sa.namespace, name=sa.name, annotations=annos
                )
                return

    def exec_in_pod(
        self,
        namespace: str,
        pod: str,
        command: list[str],
        container: str | None = None,
    ) -> str:
        return self.exec_responses.get((namespace, pod), "")
