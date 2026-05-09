"""Disable rich/click ANSI colorization for CLI smoke tests.

Help-text assertions search for plain substrings like ``--cluster``. When rich
emits color, typer/click 0.25/8.3 splits the leading ``-`` from the rest of the
flag with an ANSI reset in between (``\\x1b[1;36m-\\x1b[0m\\x1b[1;36m-cluster\\x1b[0m``),
which makes the substring search fail. CI runners set ``FORCE_COLOR``, dev
shells usually don't — so the failure only shows up in CI.

Forcing ``NO_COLOR=1`` (and clearing ``FORCE_COLOR``) here keeps the assertions
robust regardless of the surrounding environment.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_cli_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
