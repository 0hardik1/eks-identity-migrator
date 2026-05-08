"""K8s API exception wrapper (spec §15)."""

from __future__ import annotations


class K8sOperationError(Exception):
    """Wraps kubernetes.client.exceptions.ApiException with action context."""

    def __init__(
        self,
        action: str,
        message: str,
        *,
        sa: str | None = None,
        namespace: str | None = None,
        original: Exception | None = None,
    ) -> None:
        self.action = action
        self.sa = sa
        self.namespace = namespace
        self.original = original
        prefix = f"K8s {action}"
        if sa:
            scope = f"{namespace}/{sa}" if namespace else sa
            prefix += f" for SA {scope}"
        elif namespace:
            prefix += f" in namespace {namespace}"
        super().__init__(f"{prefix}: {message}")
