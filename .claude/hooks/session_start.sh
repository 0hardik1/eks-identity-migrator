#!/usr/bin/env bash
# SessionStart hook for eks-identity-migrator.
#
# Ensures the dev environment is ready and the verify gate is green so an
# incoming Claude session sees the project's baseline state on first attach.
# This makes the project "verifiable for AI agents" — a single command tells
# you whether everything still works.

# CLAUDE_PROJECT_DIR is set by the harness when invoked as a hook; fall back
# to the script's parent dirs when invoked directly for debugging.
if [[ -z "${CLAUDE_PROJECT_DIR:-}" ]]; then
  CLAUDE_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

if ! command -v uv >/dev/null 2>&1; then
  echo "[session_start] uv not installed — skipping verify."
  echo "[session_start] Install uv: https://docs.astral.sh/uv/getting-started/installation/"
  exit 0
fi

echo "[session_start] uv sync (frozen) ..."
if ! uv sync --frozen --all-extras --dev >/dev/null 2>&1; then
  echo "[session_start] uv sync failed — running unfrozen sync (lockfile may need update)."
  uv sync --all-extras --dev >/dev/null 2>&1 || {
    echo "[session_start] uv sync still failing — investigate before working."
    exit 0
  }
fi

echo "[session_start] make verify ..."
if uv run make verify > /tmp/eim-verify.log 2>&1; then
  TESTS=$(grep -oE '[0-9]+ passed' /tmp/eim-verify.log | head -1)
  COVER=$(grep -oE 'TOTAL.*[0-9]+%' /tmp/eim-verify.log | tail -1)
  echo "[session_start] verify OK — ${TESTS:-tests passed}, ${COVER:-coverage}"
else
  echo "[session_start] verify FAILED — last 30 lines below; full log at /tmp/eim-verify.log"
  echo "----------------------------------------"
  tail -30 /tmp/eim-verify.log
  echo "----------------------------------------"
fi

exit 0
