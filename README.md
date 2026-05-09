# eks-identity-migrator

Audit a cluster's IRSA usage, generate a safe migration plan to **EKS Pod Identity**, and apply it incrementally with verification and rollback.

> **Status:** v0.1 — Python implementation. See `docs/SPEC.md` for the full specification.

## Why

EKS supports two ways for pods to obtain AWS credentials:

- **IRSA (IAM Roles for Service Accounts)** — older, OIDC-based.
- **EKS Pod Identity** — newer, AWS-recommended, uses the `pods.eks.amazonaws.com` service principal and Pod Identity Associations stored in the EKS control plane.

Migrating an existing cluster is mechanical for ~70% of cases but contains landmines (multi-cluster role reuse, cross-account assumption, custom OIDC claim conditions, etc.). This tool inventories your IRSA usage, classifies each mapping for safety, generates a reviewable plan, applies it in three phases (trust → association → cleanup), verifies, and rolls back when needed.

## Learn more

For an in-depth conceptual walk-through (how OIDC + IRSA work, how Pod Identity works, and why Pod Identity is the recommended path), see [`docs/learn/`](docs/learn/README.md). The engineering specification lives in [`docs/SPEC.md`](docs/SPEC.md).

## Install

Requires Python 3.11+.

```bash
# with uv (recommended)
uv tool install eks-identity-migrator

# or pipx
pipx install eks-identity-migrator
```

## Quickstart

```bash
# 1. Read-only audit of a cluster
eks-identity-migrator audit --cluster my-cluster --region us-west-2

# 2. Generate a migration plan (green-only by default)
eks-identity-migrator plan --cluster my-cluster --strategy append --out plan.yaml

# Review plan.yaml; comment out rows you aren't ready for.

# 3. Apply phases
eks-identity-migrator apply --plan plan.yaml --phase trust --dry-run
eks-identity-migrator apply --plan plan.yaml --phase trust
eks-identity-migrator apply --plan plan.yaml --phase association

# 4. Bounce or restart pods so SDKs pick up the new credential source.

# 5. Verify and clean up
eks-identity-migrator verify --plan plan.yaml
eks-identity-migrator apply --plan plan.yaml --phase cleanup
```

For a one-shot green-only migration with verification gates between phases:

```bash
eks-identity-migrator migrate --cluster my-cluster
```

## Commands

| Command | Purpose |
|---|---|
| `audit` | Read-only inventory + risk classification |
| `plan` | Generate `plan.yaml` |
| `apply --phase {trust,association,cleanup}` | Execute one phase |
| `verify` | Confirm post-migration credential source per pod |
| `rollback --phase ...` | Reverse a phase using the journal |
| `migrate` | Convenience: green-only, all phases, with verification gates |

Run `eks-identity-migrator <cmd> --help` for full flags.

## Risk classification

Each (ServiceAccount → Role) mapping is classified:

- **green** — safe to auto-migrate.
- **yellow** — migratable with review (e.g., wildcard `sub`, multi-statement trust policy, well-known operator SA).
- **red** — breaking change requires human decision (e.g., cross-account, custom `aud` claim, multi-cluster role reuse with `--strategy replace`).
- **gray** — insufficient information (role not found, parse error, stale annotation).

## FAQ

### My role is shared across clusters. Will this break the others?

No, with the default `--strategy append`. The trust phase **adds** a Pod Identity statement next to the existing OIDC statements; other clusters keep working. `--strategy replace` would strip OIDC trust — the classifier will mark this red if the role is referenced by other OIDC issuers, blocking accidental damage. Use `replace` only after you've confirmed no other clusters use the role.

### Cross-account IRSA — what's the workaround?

Pod Identity Associations are same-account only. The recommended pattern is to create an intermediate role in the cluster's account that assumes the cross-account target role, then migrate the intermediate to Pod Identity. This tool flags cross-account roles as **red** and skips them; you build the intermediate role separately.

### My ALB controller / Karpenter / cluster-autoscaler is annotated. Can I migrate it?

The audit will mark it **yellow** with `OPERATOR_MANAGED`. Each operator has its own Pod Identity migration story (Helm chart values, controller flags). v0.1 will not auto-migrate operators — check the operator's docs first.

### Does this run any code in my cluster?

`audit`, `plan`, `verify`, `rollback`, and `apply --dry-run` are read-only against AWS and K8s (verify makes one `exec` call per SA only with `--probe`). `apply` mutates IAM trust policies, EKS Pod Identity Associations, and SA annotations — every mutation is journaled to `.eks-identity-migrator/journal-<ts>.json` for rollback.

## Limitations

Quoting spec §2 non-goals:

- **No reverse migration** to IRSA from anything else.
- **No application-code rewriting.** If your app reads `AWS_WEB_IDENTITY_TOKEN_FILE` directly, the tool flags it; humans fix it.
- **One cluster at a time.** Multi-cluster orchestration is out of scope.
- **No cross-account Pod Identity automation.** Detection + warning only.
- **CLI only.** No web UI in v0.1.

## Development

See `CLAUDE.md` for project layout, conventions, and how to run the verification gate.

```bash
make install          # uv sync --all-extras --dev
make verify           # ruff + mypy --strict + pytest + coverage gates
make integration      # kind + localstack (requires bootstrap-integration first)
```

## License

Apache-2.0.
