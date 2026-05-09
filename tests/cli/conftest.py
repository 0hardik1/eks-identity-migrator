"""Disable typer/rich ANSI colorization for CLI smoke tests.

Help-text assertions search for plain substrings like ``--cluster``. With color
on, typer/click 0.25/8.3 splits the leading ``-`` from the rest of the flag
with ANSI styling tokens in between
(``\\x1b[1;36m-\\x1b[0m\\x1b[1;36m-cluster\\x1b[0m``), and the substring search
fails.

Typer's ``rich_utils`` enables color whenever ``GITHUB_ACTIONS``, ``FORCE_COLOR``,
or ``PY_COLORS`` is set, ignoring ``NO_COLOR``. The official escape hatch is
``_TYPER_FORCE_DISABLE_TERMINAL`` — but it's read at module-import time, so it
has to be set before ``typer.rich_utils`` is loaded. We do that here at conftest
module top, which pytest loads before importing any test module that pulls in
typer.
"""

from __future__ import annotations

import os

os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)
os.environ.pop("PY_COLORS", None)
