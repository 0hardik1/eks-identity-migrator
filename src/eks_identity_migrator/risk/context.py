"""MappingContext — everything a classifier rule needs that isn't in the trust policy itself."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PodEnvVar:
    name: str
    value: str | None = None
    value_from_kind: str | None = None  # "fieldRef" / "secretKeyRef" / etc.


@dataclass(frozen=True)
class MappingContext:
    """Everything the classifier needs about an SA-to-role mapping.

    `cluster_oidc_issuer` is the OIDC issuer URL of *this* cluster — the
    classifier compares federated principals against it to detect
    cross-cluster role reuse (gotcha 1) and foreign-issuer roles.
    """

    cluster_name: str
    cluster_arn: str
    cluster_account: str
    cluster_oidc_issuer: str
    sa_namespace: str
    sa_name: str
    role_account: str | None = None
    permission_boundary: str | None = None
    pod_envs: tuple[PodEnvVar, ...] = field(default_factory=tuple)
    used_by_pods_count: int = 0

    @property
    def normalized_issuer(self) -> str:
        """Return the issuer in the same form used inside Federated principals.

        Example: `https://oidc.eks.us-west-2.amazonaws.com/id/EX` →
        `oidc.eks.us-west-2.amazonaws.com/id/EX`.
        """
        if self.cluster_oidc_issuer.startswith("https://"):
            return self.cluster_oidc_issuer[len("https://") :]
        return self.cluster_oidc_issuer
