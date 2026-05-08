"""K8s client Protocol + kubernetes-library implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from eks_identity_migrator.k8s.errors import K8sOperationError

IRSA_ANNOTATION = "eks.amazonaws.com/role-arn"


@dataclass(frozen=True)
class ServiceAccountRef:
    namespace: str
    name: str
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PodInfo:
    namespace: str
    name: str
    service_account: str  # default-SA-expanded
    phase: str  # "Running", "Pending", etc.
    owner: str  # "Deployment/foo" / "DaemonSet/bar" / ""
    container_envs: dict[str, list[tuple[str, str | None, str | None]]] = field(
        default_factory=dict
    )
    """container_name -> [(env_name, value, value_from_kind)]"""


@runtime_checkable
class K8sClient(Protocol):
    def list_service_accounts(self, namespace: str | None = None) -> list[ServiceAccountRef]: ...

    def list_pods(self, namespace: str | None = None) -> list[PodInfo]: ...

    def patch_service_account_annotations(
        self, namespace: str, name: str, annotations_patch: dict[str, str | None]
    ) -> None: ...

    def exec_in_pod(
        self,
        namespace: str,
        pod: str,
        command: list[str],
        container: str | None = None,
    ) -> str: ...


def _normalize_sa_name(spec_sa: str | None) -> str:
    if not spec_sa:
        return "default"
    return spec_sa


class KubernetesClient:
    """kubernetes-library backed K8sClient."""

    def __init__(self) -> None:
        from kubernetes import client as k8s_client

        self._core = k8s_client.CoreV1Api()
        self._client_module = k8s_client

    # ---- discovery -------------------------------------------------------

    def list_service_accounts(self, namespace: str | None = None) -> list[ServiceAccountRef]:
        from kubernetes.client.exceptions import ApiException

        try:
            if namespace:
                resp = self._core.list_namespaced_service_account(namespace=namespace)
            else:
                resp = self._core.list_service_account_for_all_namespaces()
        except ApiException as exc:
            raise K8sOperationError(
                "list_service_accounts", str(exc), namespace=namespace, original=exc
            ) from exc
        return [
            ServiceAccountRef(
                namespace=item.metadata.namespace,
                name=item.metadata.name,
                annotations=dict(item.metadata.annotations or {}),
            )
            for item in resp.items
        ]

    def list_pods(self, namespace: str | None = None) -> list[PodInfo]:
        from kubernetes.client.exceptions import ApiException

        try:
            if namespace:
                resp = self._core.list_namespaced_pod(namespace=namespace)
            else:
                resp = self._core.list_pod_for_all_namespaces()
        except ApiException as exc:
            raise K8sOperationError(
                "list_pods", str(exc), namespace=namespace, original=exc
            ) from exc

        out: list[PodInfo] = []
        for pod in resp.items:
            owner = ""
            owners = pod.metadata.owner_references or []
            if owners:
                first = owners[0]
                owner = f"{first.kind}/{first.name}"
            envs: dict[str, list[tuple[str, str | None, str | None]]] = {}
            for c in pod.spec.containers or []:
                container_envs: list[tuple[str, str | None, str | None]] = []
                for e in c.env or []:
                    val_from = None
                    if getattr(e, "value_from", None):
                        # e.value_from has fields like field_ref / secret_key_ref / etc.
                        for kind in (
                            "field_ref",
                            "secret_key_ref",
                            "config_map_key_ref",
                            "resource_field_ref",
                        ):
                            if getattr(e.value_from, kind, None):
                                val_from = kind
                                break
                    container_envs.append((e.name, e.value, val_from))
                envs[c.name] = container_envs
            out.append(
                PodInfo(
                    namespace=pod.metadata.namespace,
                    name=pod.metadata.name,
                    service_account=_normalize_sa_name(pod.spec.service_account_name),
                    phase=(pod.status.phase or "Unknown") if pod.status else "Unknown",
                    owner=owner,
                    container_envs=envs,
                )
            )
        return out

    # ---- mutations -------------------------------------------------------

    def patch_service_account_annotations(
        self, namespace: str, name: str, annotations_patch: dict[str, str | None]
    ) -> None:
        from kubernetes.client.exceptions import ApiException

        body: dict[str, Any] = {"metadata": {"annotations": annotations_patch}}
        try:
            self._core.patch_namespaced_service_account(
                name=name,
                namespace=namespace,
                body=body,
                _content_type="application/merge-patch+json",
            )
        except ApiException as exc:
            raise K8sOperationError(
                "patch_service_account",
                str(exc),
                sa=name,
                namespace=namespace,
                original=exc,
            ) from exc

    # ---- exec ------------------------------------------------------------

    def exec_in_pod(
        self,
        namespace: str,
        pod: str,
        command: list[str],
        container: str | None = None,
    ) -> str:
        """Run `command` inside `pod`, return stdout. Used by `verify --probe`."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.stream import stream

        try:
            kwargs: dict[str, Any] = {
                "name": pod,
                "namespace": namespace,
                "command": command,
                "stderr": True,
                "stdin": False,
                "stdout": True,
                "tty": False,
            }
            if container:
                kwargs["container"] = container
            result: str = stream(self._core.connect_get_namespaced_pod_exec, **kwargs)
            return result
        except ApiException as exc:
            raise K8sOperationError(
                "exec", str(exc), sa=pod, namespace=namespace, original=exc
            ) from exc
