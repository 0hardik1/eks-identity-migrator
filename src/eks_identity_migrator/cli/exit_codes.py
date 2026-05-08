"""CLI exit codes per spec §4."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    PARTIAL = 1
    INVALID_INPUT = 2
    AWS_ERROR = 3
    K8S_ERROR = 4
