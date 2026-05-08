"""Shared CLI state — global flags collected on the typer root callback."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    YAML = "yaml"


@dataclass
class CliState:
    """Per-invocation state derived from global flags."""

    cluster: str | None = None
    region: str | None = None
    profile: str | None = None
    kubeconfig: str | None = None
    context: str | None = None
    namespace: str | None = None
    service_account: str | None = None
    output: OutputFormat = OutputFormat.TABLE
    no_color: bool = False
    verbose: int = 0
    extra: dict[str, object] = field(default_factory=dict)
