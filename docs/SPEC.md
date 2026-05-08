# eks-identity-migrator — Spec

> Audit a cluster's IRSA usage, generate a safe migration plan to EKS Pod Identity, and apply it incrementally with verification and rollback.

This spec is intended to be self-contained and agent-consumable. An implementing agent should not need to make architectural decisions to ship a working v0.1; it may need judgment on tactical library picks (table rendering, color libs, etc.).

---

## 1. Context

EKS supports two mechanisms for granting AWS permissions to pods:

- **IRSA (IAM Roles for Service Accounts).** Uses an OIDC provider per cluster. Trust is expressed in IAM via `sts:AssumeRoleWithWebIdentity` with `sub` and `aud` conditions. The pod's ServiceAccount carries the annotation `eks.amazonaws.com/role-arn`.
- **EKS Pod Identity.** Newer, AWS-recommended mechanism. Uses the `pods.eks.amazonaws.com` service principal. Trust is expressed via `sts:AssumeRole` + `sts:TagSession` with `aws:SourceAccount` and `aws:SourceArn` conditions. The mapping `(cluster, namespace, serviceaccount) → role` is stored as a Pod Identity Association via the EKS API; no SA annotation needed. Requires the `eks-pod-identity-agent` add-on.

AWS now recommends Pod Identity for new workloads. Migrating an existing cluster is mechanical for ~70% of cases but contains landmines (multi-cluster role reuse, cross-account assumption, custom OIDC claim conditions, apps that read `AWS_WEB_IDENTITY_TOKEN_FILE` directly). Existing tooling (Datadog's MKAT) audits IRSA + Pod Identity but does not migrate. This tool fills that gap.

---

## 2. Goals & Non-goals

### Goals
- Inventory every IRSA-using ServiceAccount in a target cluster, joined with its IAM role and trust-policy details.
- Classify each (SA → role) mapping as **green** (safe auto-migrate), **yellow** (migratable with review), **red** (breaking change requires human decision), or **gray** (insufficient information).
- Generate a deterministic, reviewable migration plan as a YAML artifact.
- Apply the plan incrementally, in three phases (trust-policy update → association create → SA-annotation cleanup), with idempotency.
- Verify post-migration that pods receive Pod Identity credentials, not OIDC.
- Support rollback at every phase.

### Non-goals
- Migrating *to* IRSA from anything else.
- Discovering or rewriting application code that hardcodes OIDC behavior (e.g., reads the projected JWT directly). Tool flags this; humans fix it.
- Multi-cluster orchestration. Tool operates on one cluster at a time; humans coordinate fleet rollout.
- Cross-account Pod Identity setup beyond detection + warning. Pod Identity Associations are same-account only; cross-account access requires an intermediate role and is left to the user.
- A web UI. CLI only for v0.1.

---

## 3. User personas & workflows

### Primary persona
**Platform / cloud-security engineer** running EKS at moderate-to-large scale (10–500 SAs per cluster, multiple clusters, multi-account org).

### Secondary persona
**Auditor / compliance reviewer** who needs an evidence artifact that the migration was performed safely.

### Workflow

```
$ eks-identity-migrator audit --cluster my-cluster --region us-west-2
  → prints a colored table; writes audit.json

$ eks-identity-migrator plan --cluster my-cluster --strategy append --out plan.yaml
  → writes plan.yaml with per-SA migration steps

# Human reviews plan.yaml, comments out red/yellow rows they aren't ready for.

$ eks-identity-migrator apply --plan plan.yaml --phase trust --dry-run
$ eks-identity-migrator apply --plan plan.yaml --phase trust
  → updates IAM trust policies (additive — keeps OIDC trust)

$ eks-identity-migrator apply --plan plan.yaml --phase association
  → creates Pod Identity Associations

# Bounce or restart pods so SDK picks up new credential source.

$ eks-identity-migrator verify --plan plan.yaml
  → for each SA, finds a pod, exec's `aws sts get-caller-identity` style probe
    (or inspects env vars + IMDS path) to confirm Pod Identity is in use

$ eks-identity-migrator apply --plan plan.yaml --phase cleanup
  → removes the eks.amazonaws.com/role-arn annotation
  → optionally removes OIDC trust statement from the role
```

A "fast path" `eks-identity-migrator migrate` should also exist for green-only rows that runs all phases sequentially with verification gates between each.

---

## 4. CLI surface

Built with `cobra`. Binary name `eks-identity-migrator`. Global flags:

- `--cluster, -c` (required for most commands) — EKS cluster name.
- `--region, -r` — AWS region (defaults to env / config).
- `--profile` — AWS profile.
- `--kubeconfig` — path (defaults to standard).
- `--context` — kubeconfig context (defaults to current).
- `--namespace, -n` — limit scope to a single namespace.
- `--service-account` — limit scope to a single SA (requires `--namespace`).
- `--output, -o` — `table` (default) | `json` | `yaml`.
- `--no-color` — disable ANSI colors.
- `-v, --verbose` — increase log verbosity (use levels: 0 silent, 1 info, 2 debug).

Subcommands:

| Subcommand | Purpose | Writes |
|---|---|---|
| `audit` | Read-only inventory + classification | stdout, optional `audit.{json,yaml}` |
| `plan` | Generate migration artifact | `plan.yaml` |
| `apply --phase {trust,association,cleanup}` | Execute one phase | mutates AWS + K8s, writes journal |
| `verify` | Confirm migration result | stdout, exit code |
| `rollback --phase {trust,association,cleanup}` | Reverse a phase | mutates AWS + K8s |
| `migrate` | Convenience: green-only, all phases, with verification | as above |

Plan flags:
- `--strategy {append,replace}` (default: `append`). Append keeps OIDC trust during migration; replace removes it. Cleanup phase converts append → replace.
- `--include-yellow` — include yellow rows in plan (default: green only).
- `--out` — plan file path (default: `plan.yaml`).

Apply flags:
- `--plan` — path to plan file.
- `--dry-run` — print intended changes without executing.
- `--continue-on-error` — don't abort on first failure.
- `--journal` — path to write a journal of executed operations (default: `.eks-identity-migrator/journal-<timestamp>.json`).

Exit codes: `0` success, `1` partial failure, `2` invalid input, `3` AWS API error, `4` K8s API error.

---

## 5. Data model

Public types live under `pkg/types`. All structs JSON+YAML tagged.

```go
package types

type Inventory struct {
    Cluster        ClusterRef       `json:"cluster"`
    GeneratedAt    time.Time        `json:"generatedAt"`
    Mappings       []Mapping        `json:"mappings"`
    OrphanRoles    []string         `json:"orphanRoles"`    // roles with annotation but no SA
    StaleAnnotations []SARef        `json:"staleAnnotations"` // SA annotated but unused by pods
}

type ClusterRef struct {
    Name       string `json:"name"`
    Region     string `json:"region"`
    Account    string `json:"account"`
    OIDCIssuer string `json:"oidcIssuer"`
    Arn        string `json:"arn"`
}

type SARef struct {
    Namespace string `json:"namespace"`
    Name      string `json:"name"`
}

type Mapping struct {
    SA               SARef             `json:"sa"`
    RoleArn          string            `json:"roleArn"`
    TrustPolicy      json.RawMessage   `json:"trustPolicy"`
    PermissionBoundary string          `json:"permissionBoundary,omitempty"`
    UsedByPods       []PodRef          `json:"usedByPods"`
    Risk             RiskClassification `json:"risk"`
    Findings         []Finding         `json:"findings"`
}

type PodRef struct {
    Namespace string `json:"namespace"`
    Name      string `json:"name"`
    Owner     string `json:"owner"` // Deployment/StatefulSet/DaemonSet/etc
}

type RiskClassification string
const (
    RiskGreen  RiskClassification = "green"
    RiskYellow RiskClassification = "yellow"
    RiskRed    RiskClassification = "red"
    RiskGray   RiskClassification = "gray"
)

type Finding struct {
    Code     string `json:"code"`     // e.g. ROLE_USED_BY_MULTIPLE_CLUSTERS
    Severity string `json:"severity"` // info|warn|error
    Message  string `json:"message"`
    Hint     string `json:"hint,omitempty"`
}

type Plan struct {
    Cluster ClusterRef `json:"cluster"`
    Strategy string    `json:"strategy"` // append|replace
    GeneratedAt time.Time `json:"generatedAt"`
    Steps   []PlanStep `json:"steps"`
}

type PlanStep struct {
    SA          SARef             `json:"sa"`
    RoleArn     string            `json:"roleArn"`
    Risk        RiskClassification `json:"risk"`
    Skip        bool              `json:"skip,omitempty"`
    SkipReason  string            `json:"skipReason,omitempty"`
    
    TrustPolicyBefore json.RawMessage `json:"trustPolicyBefore"`
    TrustPolicyAfter  json.RawMessage `json:"trustPolicyAfter"`
    
    AssociationCreate AssociationSpec `json:"associationCreate"`
    
    AnnotationCleanup *AnnotationCleanup `json:"annotationCleanup,omitempty"`
    
    Findings []Finding `json:"findings,omitempty"`
}

type AssociationSpec struct {
    ClusterName    string `json:"clusterName"`
    Namespace      string `json:"namespace"`
    ServiceAccount string `json:"serviceAccount"`
    RoleArn        string `json:"roleArn"`
}

type AnnotationCleanup struct {
    Namespace      string `json:"namespace"`
    ServiceAccount string `json:"serviceAccount"`
    AnnotationKey  string `json:"annotationKey"` // typically eks.amazonaws.com/role-arn
}
```

---

## 6. Architecture / module layout

```
/cmd/eks-identity-migrator/main.go        # cobra wiring only
/internal/audit/                          # discovery + classification
/internal/plan/                           # plan generation
/internal/apply/                          # phase executors
/internal/verify/                         # post-migration probes
/internal/rollback/                       # journal-based reversal
/internal/k8s/                            # SA discovery, pod-using-SA enumeration, annotation patching
/internal/aws/iam/                        # role + trust-policy fetch and update
/internal/aws/eks/                        # cluster info, OIDC issuer, Pod Identity Association CRUD
/internal/aws/sts/                        # account discovery
/internal/policy/                         # trust-policy parser, translator, differ
/internal/risk/                           # classifier rules
/internal/output/                         # table, json, yaml renderers
/internal/journal/                        # journal read/write for idempotency + rollback
/pkg/types/                               # public types
/testdata/                                # JSON fixtures for trust policies, etc.
/test/integration/                        # kind + localstack tests
```

Dependency boundaries:
- `cmd` depends on `internal/*`. 
- `internal/*` may depend on each other but not on `cmd`.
- `pkg/types` has no internal deps.
- `internal/aws/*` and `internal/k8s` are the only modules that talk to remote APIs. Everywhere else takes interfaces injected at construction.

---

## 7. Core algorithms

### 7.1 Discovery

1. Resolve cluster info via `eks:DescribeCluster`. Capture: cluster ARN, OIDC issuer URL, region, account.
2. List ServiceAccounts cluster-wide (or scoped via `--namespace` / `--service-account`).
3. For each SA carrying the annotation `eks.amazonaws.com/role-arn`, capture the role ARN.
4. For each SA, list pods using it. A pod uses an SA when its `spec.serviceAccountName` equals the SA's name and the pod is in the same namespace. Default SA counts (`spec.serviceAccountName == ""` or `"default"` → namespace's default SA).
5. For each unique role ARN, fetch via `iam:GetRole` (trust policy) and `iam:GetRolePolicy` / `iam:ListAttachedRolePolicies` (only if needed for downstream features; not strictly required for v0.1).
6. Compute `Inventory`.

### 7.2 Trust-policy classifier

Given a parsed trust policy JSON, evaluate the following rules in order. First match wins for the *terminal* color; warnings can layer.

**Parser requirements:** must handle both single-statement and multi-statement policies; conditions may be `StringEquals`, `StringLike`, `ForAllValues:StringEquals`, etc.; `Principal.Federated` may be a string or an array.

**Green (auto-migratable) requires ALL of:**
- Single statement (or all statements are functionally identical in effect).
- `Effect: "Allow"`.
- `Principal.Federated` references this cluster's OIDC issuer ARN exactly.
- `Action: "sts:AssumeRoleWithWebIdentity"`.
- `Condition.StringEquals` keys are `<issuer>:aud == "sts.amazonaws.com"` and `<issuer>:sub == "system:serviceaccount:<ns>:<sa>"`.
- No other conditions.

**Yellow findings (mark yellow, allow with review):**
- Role's trust policy has *additional* statements (e.g. another SA, another cluster) — Pod Identity Association is per-(cluster, ns, sa); the additional principals can keep using OIDC. Tool emits Pod Identity for *this* SA only.
- Permission boundary attached — informational.
- `sub` uses `StringLike` with a wildcard (e.g., `system:serviceaccount:foo:*`) — bind-time scope is broader than per-SA. Tool emits a per-SA association but warns that other SAs in the namespace previously had access.
- Trust policy contains a `ForAllValues:StringEquals` with multiple `sub` values — multiple SAs share one role; emit one association per SA.
- Operator-managed SA (well-known names: `aws-load-balancer-controller`, `cluster-autoscaler`, `karpenter`, `external-dns`, `ebs-csi-controller-sa`, `efs-csi-*`, `external-secrets`) — warn that the operator's documentation should be checked for Pod Identity support before cleanup.

**Red findings (mark red, do not migrate without human):**
- `Principal.Federated` references an OIDC issuer that does NOT match this cluster's issuer — role is shared across clusters. Migration must be coordinated.
- Trust policy allows assumption from a *different account* (`Principal.AWS`) in addition to the federated principal — cross-account IRSA. Pod Identity Associations are same-account; flag for redesign.
- Trust policy contains conditions referencing OIDC-specific claims that have no Pod Identity equivalent (e.g., custom claims via OIDC `aud` with non-default value, `azp` claims).
- Pod spec hints that the application reads `AWS_WEB_IDENTITY_TOKEN_FILE` directly (heuristic: tool cannot reliably detect — emit advisory finding only when env var is explicitly set in pod spec to a custom path).

**Gray findings:**
- Role ARN in annotation does not exist (deleted) or `iam:GetRole` returns `NoSuchEntity`.
- Trust policy fails to parse.
- SA exists with annotation but no pod uses it.

The classifier must be table-driven (rule structs in `internal/risk/rules.go`) and unit-tested with at least one fixture per rule.

### 7.3 Trust-policy translation

Given the original IRSA trust policy and chosen `--strategy`:

**Append (default):** add a new statement to the existing trust policy:

```json
{
  "Effect": "Allow",
  "Principal": { "Service": "pods.eks.amazonaws.com" },
  "Action": ["sts:AssumeRole", "sts:TagSession"],
  "Condition": {
    "StringEquals": { "aws:SourceAccount": "<account>" },
    "ArnEquals":     { "aws:SourceArn":     "<cluster-arn>" }
  }
}
```

The `aws:SourceAccount` and `aws:SourceArn` conditions are **mandatory** for confused-deputy prevention and must always be emitted.

**Replace:** swap the OIDC statement(s) for the Pod Identity statement above. Only safe when no other clusters use this role; classifier already gates this.

The translator must preserve any `Sid` elements where present and pretty-print stable JSON (sorted keys at top level, 2-space indent) for deterministic diffs.

### 7.4 Apply phases

All apply operations write a journal entry *before* attempting the operation, with status `pending`, then update to `success` or `failure`. This enables idempotency (re-runs skip already-successful steps) and rollback.

**Phase: trust**
- For each non-skipped step, fetch the current trust policy. If it already equals `TrustPolicyAfter`, skip with `already-applied`. Otherwise, call `iam:UpdateAssumeRolePolicy`.

**Phase: association**
- For each non-skipped step, list Pod Identity Associations for `(cluster, ns, sa)`. If one exists pointing to the same role, skip. If one exists pointing to a *different* role, error (manual reconcile). Otherwise, call `eks:CreatePodIdentityAssociation`.

**Phase: cleanup**
- For each step marked successfully completed in the previous two phases, remove the SA annotation `eks.amazonaws.com/role-arn` via a JSON-merge patch.
- Optionally (`--remove-oidc-trust` flag), additionally remove the OIDC statement from the role trust policy. Default off.

### 7.5 Verify

For each SA in the plan with status `complete`:
1. Find one running pod using the SA.
2. Inspect pod's environment for either `AWS_CONTAINER_CREDENTIALS_FULL_URI` (Pod Identity) or `AWS_WEB_IDENTITY_TOKEN_FILE` (IRSA). Both may coexist during append-strategy migration; the SDK preference order is documented and depends on version.
3. Optionally (`--probe`) `kubectl exec` `aws sts get-caller-identity` and inspect the response's `Arn` (Pod Identity sessions are tagged with `pods.eks.amazonaws.com` — the assumed role session name encodes the SA).
4. Mark each SA verified, partially verified, or failed.

Verify is read-only; it must never mutate.

### 7.6 Rollback

Read the journal, walk operations in reverse order. Each operation type has a known inverse:
- `iam:UpdateAssumeRolePolicy` → restore from journaled `before` state.
- `eks:CreatePodIdentityAssociation` → `eks:DeletePodIdentityAssociation`.
- SA annotation removal → re-apply the journaled annotation.

If an operation has no recorded `before` state (corrupted journal), abort with a clear error rather than guess.

---

## 8. Edge cases & known gotchas

The implementing agent should encode each of these as a unit test and a documented finding code:

1. **Multi-cluster role reuse.** Same role used by IRSA in clusters A and B. Migrating cluster A must NOT remove cluster B's OIDC trust. Append strategy must preserve all OIDC statements; replace strategy must be blocked.

2. **Cross-account direct IRSA.** A role in account 222 trusted by an OIDC issuer in account 111. Pod Identity does not support cross-account directly. Mark red. Document the workaround (intermediate role in same account assuming the cross-account role).

3. **`StringLike` / wildcard `sub`.** `sub` like `system:serviceaccount:ns:*` allows multiple SAs to share a role. The Pod Identity equivalent requires one Association per SA. Tool must enumerate the SAs *currently* using this role and emit per-SA associations; warn that future SAs added to the namespace will not auto-inherit access.

4. **Multiple SAs to one role via `ForAllValues:StringEquals`.** Same handling — emit per-SA associations.

5. **`aud` claim is non-default.** If `aud` is anything other than `sts.amazonaws.com`, that's a custom OIDC integration; Pod Identity has no equivalent. Mark red.

6. **Permission boundary.** Permission boundaries on the IAM role are unaffected by trust-policy changes. Surface as informational only.

7. **Stale annotation.** SA carries annotation but no pod uses the SA. Mark gray; do not migrate.

8. **Default SA usage.** Pods with empty `spec.serviceAccountName` use the namespace's `default` SA. If that default SA is annotated, all pods in the namespace pick it up. Surface this clearly.

9. **DaemonSet / operator SAs.** Common patterns (`aws-load-balancer-controller`, `karpenter`, `cluster-autoscaler`, AWS CSI drivers, `external-dns`, `external-secrets`). Each operator may have its own Pod Identity migration story. Tool emits a yellow finding with a link placeholder per operator; v0.1 does not auto-migrate operators.

10. **Pod Identity Agent not installed.** Detect via the EKS add-on API (`eks:DescribeAddonVersions`, `eks:ListAddons`). If `eks-pod-identity-agent` is not present, refuse to run `apply --phase association` and emit an actionable error.

11. **Old AWS SDK in container.** Cannot reliably detect from outside the container. Document that SDK versions older than ~2023 may not pick up Pod Identity env vars; suggest manual verification.

12. **App reads `AWS_WEB_IDENTITY_TOKEN_FILE` directly.** Cannot statically detect. When verify step finds the pod still using OIDC after migration, emit a clear remediation hint.

13. **Long role-session-name truncation.** Pod Identity uses session names derived from the (cluster, ns, sa) tuple; deeply nested namespaces or very long SA names may hit IAM's 64-char session-name limit. Detect and warn.

14. **Same role used as both an instance profile and an IRSA target.** Trust policy will have an EC2 service principal *and* a Federated principal. Append works fine; replace is dangerous. Classifier must detect.

15. **`sts:TagSession` already in trust policy.** Some pre-existing IRSA roles include it; the tool's translator should de-duplicate when assembling the new statement.

16. **IAM rate limits.** `iam:GetRole` is throttled. For large clusters, batch with backoff. Use `aws-sdk-go-v2`'s built-in retry but configure max attempts ≥ 5 with adaptive mode.

17. **Pods scheduled but not yet running during verify.** Skip non-Running pods; report as "verification deferred" rather than failure.

---

## 9. Output formats

### Audit table (default)

```
NAMESPACE       SA                          ROLE                              RISK    FINDINGS
production      app-frontend                arn:aws:iam::...:role/frontend    GREEN   -
production      app-worker                  arn:aws:iam::...:role/worker      YELLOW  WILDCARD_SUB
kube-system     aws-load-balancer-ctrl      arn:aws:iam::...:role/alb         YELLOW  OPERATOR_MANAGED
data            etl-pipeline                arn:aws:iam::...:role/etl         RED     CROSS_ACCOUNT_TRUST
infra           legacy-tool                 arn:aws:iam::...:role/legacy      GRAY    STALE_ANNOTATION

5 ServiceAccounts: 1 GREEN, 2 YELLOW, 1 RED, 1 GRAY
Run `eks-identity-migrator audit -o json` for full details.
```

Color: green/yellow/red/gray for risk column; muted gray for findings unless severity ≥ warn.

### Plan YAML

```yaml
cluster:
  name: my-cluster
  region: us-west-2
  account: "123456789012"
  arn: arn:aws:eks:us-west-2:123456789012:cluster/my-cluster
strategy: append
generatedAt: 2026-05-08T14:32:00Z
steps:
  - sa: { namespace: production, name: app-frontend }
    roleArn: arn:aws:iam::123456789012:role/frontend
    risk: green
    trustPolicyBefore: { ... }
    trustPolicyAfter:  { ... }
    associationCreate:
      clusterName: my-cluster
      namespace: production
      serviceAccount: app-frontend
      roleArn: arn:aws:iam::123456789012:role/frontend
    annotationCleanup:
      namespace: production
      serviceAccount: app-frontend
      annotationKey: eks.amazonaws.com/role-arn
  - sa: { namespace: data, name: etl-pipeline }
    roleArn: arn:aws:iam::222222222222:role/etl
    risk: red
    skip: true
    skipReason: CROSS_ACCOUNT_TRUST
    findings:
      - code: CROSS_ACCOUNT_TRUST
        severity: error
        message: Role lives in a different account; Pod Identity Associations are same-account only.
        hint: Create a same-account intermediate role that assumes the target role; migrate that intermediate to Pod Identity.
```

### Journal

NDJSON (one JSON object per line). Each line:

```json
{"ts":"2026-05-08T14:35:01Z","op":"iam:UpdateAssumeRolePolicy","status":"success","sa":{"namespace":"production","name":"app-frontend"},"before":{...},"after":{...}}
```

---

## 10. Testing

### Unit tests
- Trust-policy parser: at least 20 fixtures in `testdata/trust-policies/` covering every rule in §7.2. Each fixture is a paired `.in.json` (raw policy) and `.expected.json` (parsed structure + classifier output).
- Trust-policy translator: ≥ 10 fixtures covering append/replace × edge cases.
- Risk classifier: parameterized table test with one row per finding code.
- Journal idempotency: rerun applies ≥ 3 times against the same mocked AWS state and assert no additional API calls beyond the first run.

### Integration tests
- `kind` cluster + `localstack` (community edition supports IAM and minimal EKS APIs; if EKS coverage is insufficient, fall back to mocking `internal/aws/eks` at the interface boundary while keeping IAM real).
- Test matrix: green-only migrate, mixed plan with skips, append→replace transition, rollback after each phase.

### Linters / quality gates
- `golangci-lint` with `errcheck`, `govet`, `staticcheck`, `revive` enabled.
- Test coverage gate: ≥ 80% on `internal/policy`, `internal/risk`, `internal/plan`. Other packages ≥ 60%.

---

## 11. Dependencies

Pinned to known-stable major versions; agent should pick latest minor at implementation time:

- `github.com/aws/aws-sdk-go-v2` and the `iam`, `eks`, `sts` service clients
- `k8s.io/client-go` and `k8s.io/api`
- `github.com/spf13/cobra` — CLI framework
- `github.com/spf13/pflag` — flags (transitive via cobra)
- `gopkg.in/yaml.v3` — YAML
- `github.com/fatih/color` — terminal color (optional; gate behind `--no-color`)
- `github.com/olekukonko/tablewriter` — table rendering (optional alternative: hand-rolled)

No CGO. Single static binary. Linux/macOS/Windows builds via GoReleaser.

---

## 12. Acceptance criteria

The implementing agent should consider v0.1 complete when:

1. **`audit`** runs against a real EKS cluster of ≥ 50 SAs in < 30 seconds, producing accurate inventory with classifications. All 16 gotchas in §8 are encoded as test fixtures and the classifier emits the documented finding code.
2. **`plan`** produces a YAML artifact that round-trips losslessly (load → marshal → load yields identical structure). Plans for the same cluster state are deterministic byte-for-byte.
3. **`apply --dry-run`** prints every intended API call without making any. Verified by running with an `iam:*` Deny in the caller's policy.
4. **`apply`** is idempotent: running it twice on a green-only plan produces the same end state and a journal where the second run records 0 mutations.
5. **`verify`** correctly distinguishes IRSA-only, Pod-Identity-only, and dual-trust pods.
6. **`rollback --phase association`** removes Pod Identity Associations created by a prior `apply --phase association` and the role's trust policy reverts to its pre-migration state when invoked through `--phase trust` rollback.
7. **README** contains: install, quickstart against `kind`, full migration walkthrough, FAQ entries for cross-account, multi-cluster, and operator SAs, and a clearly labeled "limitations" section quoting §2 non-goals.
8. **Security:** the binary makes no outbound network calls beyond the AWS APIs and the configured K8s API server. No telemetry, no version-check pings.

---

## 13. Out of scope / future work

Tracked here so the agent does not implement them in v0.1:

- Multi-cluster orchestration / fleet rollout.
- Cross-account Pod Identity automation (intermediate role generation).
- Auto-migration of well-known operators (ALB controller, Karpenter, etc.).
- A continuous "drift detector" that watches for new IRSA SAs after migration.
- Web UI / TUI.
- Helm-chart-aware mode that rewrites chart values for Pod Identity.
- Direct integration with Crossplane / ACK for IaC-driven rollout.
- Generating SOC 2 / ISO 27001 evidence packets from the journal.

---

## 14. References

- AWS docs: *Learn how EKS Pod Identity grants pods access to AWS services* (`docs.aws.amazon.com/eks/latest/userguide/pod-identities.html`).
- AWS docs: *IAM roles for service accounts* (`docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html`).
- EKS Best Practices Guide — Identity and Access Management section (`aws.github.io/aws-eks-best-practices/security/docs/iam/`).
- Datadog Security Labs: *Deep dive into the new Amazon EKS Pod Identity feature* — useful for understanding the agent's runtime mechanics including the link-local API.
- AWS confused-deputy guidance: `aws:SourceAccount` and `aws:SourceArn` condition keys.

---

## 15. Notes for the implementing agent

- **Resist the urge to scope-creep into runtime detection or operator auto-migration.** The non-goals in §2 exist because each is a substantial project on its own.
- **Treat the journal as a first-class artifact.** It is the rollback substrate, the audit evidence, and the idempotency check. Get its format right before writing apply logic.
- **Trust-policy comparison is JSON-semantic, not byte-equal.** Two policies that differ only in whitespace, key ordering, or `Sid` presence are equivalent for the purpose of "already applied" checks. Implement a canonicalizer in `internal/policy` and use it everywhere.
- **Default to safety.** When in doubt, classify as gray or yellow rather than green. False negatives on classification (i.e., wrongly green) are far worse than false positives.
- **Print actionable errors.** Never bubble up a raw `*smithy.OperationError` to the user. Wrap with the action that was being attempted and the SA in question.
- **Do not parallelize AWS writes by default.** Trust-policy updates are infrequent and the throttling cost of a serial loop is invisible at < 500 roles. Add `--concurrency` later if needed.
