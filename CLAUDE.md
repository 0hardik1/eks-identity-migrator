# CLAUDE.md

Onboarding for Claude (and other agents) working on this repository.

## What this is

A Python CLI that audits an EKS cluster's IRSA usage and migrates it to EKS Pod Identity. The full specification is in `docs/SPEC.md` — that document is the source of truth; this file summarizes how the codebase implements it.

## Layout

```
src/eks_identity_migrator/
├── cli/         # typer wiring; one file per subcommand (audit, plan, apply, verify, rollback, migrate)
├── types/       # pydantic v2 models (inventory, plan, journal); _base.py defines the camelCase BaseModel
├── policy/      # parser, canonicalizer, translator, differ — JSON-semantic trust-policy ops
├── risk/        # codes (StrEnum), operators (well-known SA registry), rules (table-driven classifier)
├── audit/       # discovery + joiner — turns AWS+K8s reads into an Inventory
├── plan/        # generator + io — turns an Inventory into a Plan and round-trips YAML
├── apply/       # runner + trust + association + cleanup — every op is journal-wrapped
├── verify/      # probe + result — inspect pod env / sts:GetCallerIdentity
├── rollback/    # journal_walker + inverses — replay journal in reverse
├── journal/     # NDJSON writer + reader
├── output/      # table (rich), json_render, yaml_render, colors
├── aws/         # session, iam, eks, sts, errors — Protocols + boto3 implementations
└── k8s/         # client, config, errors — Protocol + kubernetes implementation
```

## Hard rules

1. **Boundary rule.** Only modules under `src/eks_identity_migrator/aws/` and `src/eks_identity_migrator/k8s/` may `import boto3` or `import kubernetes`. Everywhere else takes Protocol classes by injection. Enforced by `tests/test_imports.py`.
2. **Trust-policy equality is JSON-semantic, not byte-equal.** Always go through `policy/canonicalizer.py` for comparisons. IAM-returned policies are URL-decoded by botocore — pass directly to `policy/parser.py`.
3. **All AWS/K8s mutations are journaled.** `apply/runner.py` writes `pending` → `success`/`failure` entries before any side effect. This is the rollback substrate.
4. **All public model output uses camelCase.** Pydantic models extend `types._base.CamelModel`; render with `model_dump_json(by_alias=True)`. JSON output is sorted-key, 2-space indented.
5. **No silent error wrapping.** Wrap botocore `ClientError` in `aws/errors.AwsOperationError` with the action and the SA in question. Same for `kubernetes.ApiException` → `k8s/errors.K8sOperationError`.
6. **Coverage gates** (enforced by `make verify`):
   - `policy/`, `risk/`, `plan/` — ≥80%
   - everything else — ≥60%

## Commands

```bash
make install            # uv sync --all-extras --dev (one time)
make verify             # ruff fmt-check + ruff lint + mypy --strict + pytest + coverage gates
make fmt                # auto-format
make integration        # kind + localstack (run `make bootstrap-integration` first)
uv run eks-identity-migrator --help
```

Run `make verify` before every commit. CI mirrors it.

## SessionStart hook

`.claude/settings.json` registers a SessionStart hook that runs
`uv sync --frozen` and `make verify` on every Claude session start. The hook
prints either:
- `[session_start] verify OK — N passed, COVER%` — baseline is green, you can
  start working immediately.
- `[session_start] verify FAILED — last 30 lines below; full log at
  /tmp/eim-verify.log` — fix the gate before adding code.

This makes the project self-explaining for incoming agents: a single line tells
you whether the codebase is in a known-good state.

## Where to add things

- **A new finding code** → add to `risk/codes.py` (`FindingCode` StrEnum), add a `Rule` to `risk/rules.py`, add a fixture pair under `testdata/trust-policies/<NN>_<name>.{in,expected}.json`.
- **A new AWS API call** → add a method to the appropriate `Protocol` in `aws/<service>.py`, implement on the boto class in the same file, mock with `moto` in tests.
- **A new K8s API call** → same pattern in `k8s/client.py`. For `exec`-style streaming, use the existing wrapper.
- **A new CLI subcommand** → new file in `cli/`, register in `cli/__init__.py`. Keep the file thin: parse args → call orchestrator → render result.
- **A new edge case in the trust-policy classifier** → write the failing fixture first, then add the rule.

## Don't do (per spec §15)

- Don't scope-creep into runtime detection or operator auto-migration.
- Don't parallelize AWS writes by default — keep apply serial.
- Don't bubble up raw `*ClientError` / `ApiException`.
- Don't compare trust policies as bytes — always canonicalize first.
- Don't classify as green when in doubt — prefer yellow or gray.

## Spec-derived invariants

- Pod Identity statement always includes both `aws:SourceAccount` (StringEquals) and `aws:SourceArn` (ArnEquals) for confused-deputy prevention.
- `--strategy append` keeps existing OIDC statements; `--strategy replace` strips OIDC but preserves non-OIDC principals (e.g., EC2 service principal — gotcha 14).
- `eks-pod-identity-agent` addon must be present before `apply --phase association` runs (gotcha 10).

## Active limitations

- Pod Identity Associations are same-account only. Cross-account roles are flagged red and skipped.
- LocalStack EKS Pod Identity API coverage is incomplete; integration tests use a fake EKS at the Protocol boundary while keeping IAM real on LocalStack.
- Acceptance §12.1 (≥50 SAs in <30s) can only be measured against a real EKS cluster.
- mypy is pinned `<2.0` because mypy 2.0.0 has a regression on `disable_error_code` in `tool.mypy.overrides`.
