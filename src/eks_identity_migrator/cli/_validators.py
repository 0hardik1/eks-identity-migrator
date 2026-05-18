"""Shared CLI input validators.

Each validator either returns the validated value or raises ``typer.BadParameter``
(which typer converts to exit code 2 with a friendly message). Centralised here
so ``plan`` and ``migrate`` validate ``--strategy`` identically and so the
educational error message stays in one place.
"""

from __future__ import annotations

import typer

_VALID_STRATEGIES = frozenset({"append", "replace"})


def validate_strategy(strategy: str) -> str:
    """Validate ``--strategy``. Returns the value or raises ``typer.BadParameter``.

    The error message explains both options so a first-time user learns the
    safety implications without leaving the terminal.
    """
    if strategy in _VALID_STRATEGIES:
        return strategy
    raise typer.BadParameter(
        "must be 'append' (default — keeps existing OIDC trust statements) "
        "or 'replace' (strips OIDC trust; use only when no other cluster shares the role)",
        param_hint="--strategy",
    )
