# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] — 2026-05-08

Initial release. Implements the v0.1 spec at `docs/SPEC.md`.

### Added

- **CLI** (`typer`-based) with six subcommands:
  - `audit` — read-only IRSA inventory + risk classification
  - `plan` — generate `plan.yaml` (append/replace strategies; `--include-yellow` filter)
  - `apply --phase {trust,association,cleanup}` — execute one migration phase with journaled mutations
  - `verify` — confirm pod credential source via env-var inspection (and optional `kubectl exec`)
  - `rollback --phase ...` — replay journal in reverse with per-op inverses
  - `migrate` — convenience: green-only end-to-end with verification gate between phases
- **Risk classifier** with 17 finding codes covering every spec §8 gotcha
- **Trust-policy translator** with mandatory `aws:SourceAccount` + `aws:SourceArn`, idempotent re-translate, EC2-principal preservation under replace strategy
- **Append-only NDJSON journal** as the rollback substrate (spec §15)
- **Test suite**: 171 unit tests plus integration harness (`kind` + LocalStack IAM + fake EKS at the Protocol boundary), 86% coverage on `policy/`, `risk/`, `plan/`
- **Verifiability for AI agents**: `make verify` single-command gate, SessionStart hook in `.claude/`, CLAUDE.md onboarding, GitHub Actions CI on Python 3.11 and 3.12
- **Strict boundary**: only `aws/` and `k8s/` may import boto3/kubernetes (enforced by `tests/test_imports.py`)

### Out of scope

Per spec §13: multi-cluster orchestration, cross-account Pod Identity automation,
operator auto-migration, drift detector, web UI, Helm/Crossplane integration.
