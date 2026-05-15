"""Kubeconfig loader + active-context hint parser.

`load_kube_config()` is the production loader — wired before constructing
`KubernetesClient`. `get_current_context_hint()` is the read-only helper used
by the CLI to default `--cluster` when the user runs e.g. `make scan` without
arguments. It parses the *current context name* — not the full kubeconfig —
so we never need cluster server URLs, certs, or tokens just to guess a name.

Recognised context-name shapes:

- EKS ARN form: ``arn:aws:eks:<region>:<account>:cluster/<name>``
- eksctl form:  ``<user>@<cluster>.<region>.eksctl.io``
- Anything else: used verbatim as ``cluster_name`` with ``region=None``.
  EKS DescribeCluster will then either succeed or fail with a clear error.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextHint:
    """A best-guess cluster name + region parsed from a kubectl context name."""

    cluster_name: str
    region: str | None
    context_name: str


class KubeContextResolutionError(Exception):
    """Raised when no kubeconfig or no active context is available.

    The message is end-user facing — it should tell them how to fix it
    (run ``aws eks update-kubeconfig`` or pass ``--cluster`` explicitly).
    """


def load_kube_config(*, kubeconfig: str | None = None, context: str | None = None) -> None:
    """Load kubeconfig honouring --kubeconfig and --context. Falls back to in-cluster."""
    from kubernetes import config as k8s_config
    from kubernetes.config.config_exception import ConfigException

    try:
        k8s_config.load_kube_config(config_file=kubeconfig, context=context)
    except (FileNotFoundError, ConfigException):
        # Fallback to in-cluster (when running inside a pod with a SA token).
        k8s_config.load_incluster_config()


def parse_context_name(context_name: str) -> ContextHint:
    """Pure parser: context-name string → ContextHint. No kubeconfig I/O."""
    # EKS ARN: arn:<partition>:eks:<region>:<account>:cluster/<name>
    if context_name.startswith("arn:") and ":eks:" in context_name:
        parts = context_name.split(":")
        if len(parts) >= 6 and "/" in parts[5]:
            region = parts[3]
            cluster_name = parts[5].split("/", 1)[1]
            return ContextHint(cluster_name=cluster_name, region=region, context_name=context_name)

    # eksctl: <user>@<cluster>.<region>.eksctl.io
    if context_name.endswith(".eksctl.io") and "@" in context_name:
        after_at = context_name.split("@", 1)[1]
        # Strip the .eksctl.io suffix, then split the last dot into region.
        host = after_at.removesuffix(".eksctl.io")
        if "." in host:
            cluster_name, region = host.rsplit(".", 1)
            return ContextHint(cluster_name=cluster_name, region=region, context_name=context_name)

    # Unknown shape — use the whole context name as cluster name.
    return ContextHint(cluster_name=context_name, region=None, context_name=context_name)


def get_current_context_hint(*, kubeconfig: str | None = None) -> ContextHint:
    """Read the active kubectl context name and parse it into a ContextHint.

    Raises :class:`KubeContextResolutionError` if no kubeconfig exists or
    if there is no active context. Pass ``kubeconfig`` to override the
    default search path (``$KUBECONFIG`` or ``~/.kube/config``).
    """
    from kubernetes import config as k8s_config
    from kubernetes.config.config_exception import ConfigException

    try:
        _, active = k8s_config.list_kube_config_contexts(config_file=kubeconfig)
    except (FileNotFoundError, ConfigException) as exc:
        raise KubeContextResolutionError(
            "no kubeconfig found — run `aws eks update-kubeconfig --name <cluster>` "
            "or pass `--cluster <name>` explicitly"
        ) from exc

    if not active or not active.get("name"):
        raise KubeContextResolutionError(
            "no active kubectl context — switch with `kubectl config use-context <name>` "
            "or pass `--cluster <name>` explicitly"
        )

    return parse_context_name(active["name"])
