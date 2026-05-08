"""K8s client layer — Protocol + kubernetes-library implementation.

This is the *only* module (besides `aws/`) allowed to `import kubernetes`.
"""

from eks_identity_migrator.k8s.client import (
    IRSA_ANNOTATION,
    K8sClient,
    KubernetesClient,
    PodInfo,
    ServiceAccountRef,
)
from eks_identity_migrator.k8s.config import load_kube_config
from eks_identity_migrator.k8s.errors import K8sOperationError

__all__ = [
    "IRSA_ANNOTATION",
    "K8sClient",
    "K8sOperationError",
    "KubernetesClient",
    "PodInfo",
    "ServiceAccountRef",
    "load_kube_config",
]
