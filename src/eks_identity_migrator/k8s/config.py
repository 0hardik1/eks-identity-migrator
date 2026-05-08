"""Kubeconfig loader."""

from __future__ import annotations


def load_kube_config(*, kubeconfig: str | None = None, context: str | None = None) -> None:
    """Load kubeconfig honouring --kubeconfig and --context. Falls back to in-cluster."""
    from kubernetes import config as k8s_config
    from kubernetes.config.config_exception import ConfigException

    try:
        k8s_config.load_kube_config(config_file=kubeconfig, context=context)
    except (FileNotFoundError, ConfigException):
        # Fallback to in-cluster (when running inside a pod with a SA token).
        k8s_config.load_incluster_config()
