# IRSA vs Pod Identity: how Pod Identity solves the problem

> **What you'll get from reading this:** a concrete, problem-by-problem
> comparison of IRSA and Pod Identity, an honest list of what Pod Identity
> does *not* fix, and the rationale behind this codebase's three-phase
> `trust → association → cleanup` migration.

This document assumes you've read or skimmed
[01-oidc-and-irsa.md](01-oidc-and-irsa.md) and
[02-pod-identity.md](02-pod-identity.md). If you only have five minutes,
read the TL;DR and the comparison table below; come back for the rest when
something doesn't make sense.

---

## TL;DR (five bullets)

- **What each does:** both grant short-lived AWS credentials to pods. IRSA
  does it via per-cluster OIDC + `sts:AssumeRoleWithWebIdentity`; Pod
  Identity does it via a node-local agent + `sts:AssumeRole` against the
  `pods.eks.amazonaws.com` service principal.
- **Trust shape:** IRSA = federated principal (per-cluster OIDC ARN), with
  conditions on `<issuer>:aud` and `<issuer>:sub`. Pod Identity = service
  principal `pods.eks.amazonaws.com`, with mandatory `aws:SourceAccount`
  and `aws:SourceArn` conditions for confused-deputy prevention.
- **Credential delivery:** IRSA = SDK reads JWT file, calls STS directly.
  Pod Identity = SDK calls a local HTTP endpoint; agent calls STS on the
  pod's behalf.
- **Per-cluster setup:** IRSA = one IAM OIDC provider resource per cluster,
  trust policies enumerate every cluster's issuer. Pod Identity = zero
  per-cluster IAM resources; trust references the cluster ARN as a
  condition value.
- **Migration blast radius:** large, *if* you go fast. Small, if you use
  this tool's `--strategy append` default and the three-phase apply
  (`trust → association → cleanup`), which keeps both paths live until
  `verify` confirms the SDK has switched.

---

## Side-by-side comparison

| Dimension | IRSA | Pod Identity |
|---|---|---|
| AWS-recommended for new workloads | No (legacy) | **Yes** |
| Trust principal | `Principal.Federated` (per-cluster OIDC provider ARN) | `Principal.Service: pods.eks.amazonaws.com` |
| STS API used | `sts:AssumeRoleWithWebIdentity` | `sts:AssumeRole` + `sts:TagSession` |
| Confused-deputy conditions | None by default | **Mandatory** `aws:SourceAccount` + `aws:SourceArn` |
| OIDC `aud` claim | `sts.amazonaws.com` (or custom) | n/a |
| OIDC `sub` claim used to bind to SA | `system:serviceaccount:<ns>:<sa>` | n/a |
| Source of `(SA → role)` mapping | SA annotation `eks.amazonaws.com/role-arn` (in-cluster) | EKS Pod Identity Association (in EKS API) |
| Per-cluster IAM resources | One IAM OIDC provider per cluster | None (one shared service principal) |
| Trust-policy edits to add a new cluster | Yes — append the new cluster's issuer | No — same role works in any cluster you create an Association in |
| Cross-account access | Possible (cluster A's OIDC trusted by role in account B) | **Same-account only**; needs intermediate role |
| Multi-SA per role | Wildcard `sub` or `ForAllValues:StringEquals` | Explicit per-SA Association |
| Session tags | Hand-rolled via `sts:TagSession` plumbing | Five EKS-native tags (cluster, namespace, SA, pod name, pod UID) by default |
| Credential delivery to pod | SDK calls STS directly with JWT | SDK calls local agent (`http://169.254.170.23/v1/credentials`) with bearer |
| Credential TTL | ~1 hour | ~6 hours |
| Pod-side env vars | `AWS_ROLE_ARN`, `AWS_WEB_IDENTITY_TOKEN_FILE` | `AWS_CONTAINER_CREDENTIALS_FULL_URI`, `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE` |
| Reachability requirement | STS must reach the cluster's OIDC issuer (JWKS) | None public (agent talks to STS server-side) |
| Webhook involved | EKS pod-identity *webhook* (legacy) injects env+volume | Pod Identity service-account webhook injects env (different mechanism, different lifecycle) |
| Daemonset required | No | Yes (`eks-pod-identity-agent` addon) |
| Per-pod observability | JWT claims in token file (visible inside pod) | Session tags surface in CloudTrail and condition keys |
| Rollback granularity | Edit role trust + remove SA annotation | Delete Association + (optionally) remove Pod Identity statement |
| Where this codebase classifies | [`risk/codes.py`](../../src/eks_identity_migrator/risk/codes.py) finding codes | Pre-flight + apply phases in [`apply/`](../../src/eks_identity_migrator/apply/) |

---

## Problem → solution walk-through

For each IRSA pain point, the IRSA behaviour quoted from the previous
chapter, then how Pod Identity removes it (or doesn't), then the matching
finding code in this codebase.

### 1. Per-cluster IAM resource sprawl

**IRSA:** One IAM OIDC provider per cluster, registered as a separate
resource. A role trusted by N clusters lists N OIDC ARNs and N condition
key prefixes (`oidc.eks.<region>.amazonaws.com/id/<id>:aud` etc.). When
you delete a cluster you must also delete its IAM OIDC provider, prune
references from any roles that mentioned it, and update IaC.

**Pod Identity:** **Zero per-cluster IAM resources.** Trust uses the
single service principal `pods.eks.amazonaws.com`; the cluster identity
shows up as a *condition value* (`aws:SourceArn = arn:aws:eks:...:cluster/<name>`),
not as a separately-managed resource. Deleting a cluster doesn't leave
IAM rubble.

> **In this codebase:** every Pod Identity statement emitted by
> [`policy/translator.py:32-56`](../../src/eks_identity_migrator/policy/translator.py)
> uses the same service principal. The cluster ARN is a condition value
> threaded through from the plan; see
> [SPEC §7.3](../SPEC.md).

### 2. Multi-cluster role reuse becomes safe

**IRSA:** A role trusted by both cluster A and cluster B carries OIDC
statements for each. Editing trust to add cluster B can break cluster A
if a careless human nukes the wrong statement; this is a real, common
operator mistake. This codebase's
`--strategy append` exists exactly because of this risk.

**Pod Identity:** Associations are per-cluster. There is no "shared trust
surface" to misedit — adding Pod Identity to a role for cluster B
doesn't touch cluster A's path. The role's trust policy still has *one*
Pod Identity statement (since the principal is the same), but each
cluster's *use* of the role is gated by a separate Association in the
EKS control plane.

> **In this codebase:** `_has_other_oidc_issuer` in
> [`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py):47–52
> emits `ROLE_USED_BY_MULTIPLE_CLUSTERS` (yellow) so the plan generator
> can refuse to use `--strategy replace` on shared roles. Append-strategy
> migration is always safe for this case.

### 3. Wildcard / multi-SA `sub` patterns

**IRSA:** `Condition.StringLike` with
`system:serviceaccount:<namespace>:*` lets every SA in a namespace share a
role. Convenient — but the *list* of SAs actually using it is implicit
(it's whatever has the annotation), and a future SA in that namespace
silently inherits AWS access.

**Pod Identity:** Per-SA Association. The active SA→role mapping is a
queryable list, every entry is an explicit AWS-side decision, and a new
SA does **not** auto-inherit access. ABAC patterns that need
namespace-scoped permissions move to permission-policy conditions on the
session tags rather than to wildcard trust.

> **In this codebase:** `WILDCARD_SUB` and `MULTI_SUB_FORALL` findings
> ([`risk/rules.py:76-96`](../../src/eks_identity_migrator/risk/rules.py))
> are yellow — migratable, but only after the audit step has enumerated
> the SAs *currently* using the role. The plan emits one Association per
> active SA. Fixtures:
> [`03_wildcard_sub.in.json`](../../testdata/trust-policies/03_wildcard_sub.in.json),
> [`04_forall_multi_sub.in.json`](../../testdata/trust-policies/04_forall_multi_sub.in.json).

### 4. Custom `aud` claims and OIDC-coupled apps

**IRSA:** The projected JWT is part of the pod's contract. Some apps use
the JWT for purposes other than `sts:AssumeRoleWithWebIdentity` — e.g.,
proving identity to a non-AWS OIDC relying party, where they need a
custom `aud`. Trust policies with `aud != sts.amazonaws.com` are usually
a sign of one of these setups.

**Pod Identity:** The token contract is internal to the agent. Apps that
just want AWS credentials don't see any token at all. Apps that wanted
the JWT for non-AWS purposes are unaffected at the SA level — they can
still mount their own projected volume — but Pod Identity itself doesn't
carry a custom audience to the pod.

> **In this codebase:** `CUSTOM_AUD_CLAIM` is **red**
> ([`risk/rules.py:99-110`](../../src/eks_identity_migrator/risk/rules.py))
> — the migration tool refuses to assume a custom-aud setup is safe to
> auto-translate, because the human almost certainly meant something
> non-trivial. Fixture:
> [`05_custom_aud_claim.in.json`](../../testdata/trust-policies/05_custom_aud_claim.in.json).
> The remediation is per-case, not generic.

### 5. Confused-deputy hardening built in

**IRSA:** Trust policies *can* include
[`aws:SourceAccount`](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)
and similar guards, but it's not standard practice — most hand-written
or `eksctl`-emitted IRSA trust has only the OIDC `sub`/`aud` conditions.
That's enough to scope to one SA in one cluster, but if the OIDC issuer
ARN is reused across accounts (it shouldn't be, but mistakes happen) the
guard isn't there.

**Pod Identity:** This codebase, following AWS guidance and
[SPEC §7.3](../SPEC.md), **always emits both**
`aws:SourceAccount` (StringEquals) and `aws:SourceArn` (ArnEquals). The
translator
[`policy/translator.py:44-47`](../../src/eks_identity_migrator/policy/translator.py)
hard-codes them; there's no flag to opt out. Even if you were to
hand-edit a trust policy without these conditions, AWS recommends them
strongly enough that omission is itself a finding worth flagging in
internal review.

### 6. Session tags for free

**IRSA:** Session tags require `sts:TagSession` in the trust action list
plus `aws:RequestTag`/`aws:PrincipalTag` plumbing on the *role*'s
permission policies *and* matching tags passed by the assuming party.
Most IRSA setups don't bother — they encode tenant identity in role
names instead, which doesn't scale.

**Pod Identity:** EKS injects five canonical tags
(`eks-cluster-name`, `kubernetes-namespace`, `kubernetes-service-account`,
`kubernetes-pod-name`, `kubernetes-pod-uid`) on every assumption,
automatically. ABAC like "this role can only write to S3 prefixes that
match `${aws:PrincipalTag/kubernetes-namespace}`" works out of the box.

> **In this codebase:** the translator emits `sts:TagSession` in the
> action list of every Pod Identity statement
> ([`policy/translator.py:29`](../../src/eks_identity_migrator/policy/translator.py)).
> The classifier emits the informational
> `STS_TAGSESSION_PRESENT` finding when an existing IRSA policy already
> has `sts:TagSession` so you know de-duplication is in play.

### 7. No more public JWKS exposure

**IRSA:** STS reaches the cluster's OIDC issuer endpoint to fetch JWKS —
the issuer URL must be reachable from AWS. EKS managed issuers are
publicly reachable; air-gapped or private clusters need extra plumbing.
The endpoint is read-only and exposes only public keys, but it is one
more public attack surface to monitor.

**Pod Identity:** STS does not reach the cluster. The agent on each node
talks to AWS server-side; the cluster's outbound path to the EKS API and
STS is the only network requirement. There is no public JWKS endpoint
in the trust path.

### 8. Credential lifetime

**IRSA:** ~1 hour by default. Apps that hold credentials in caches
longer than the SDK's refresh interval can hit `ExpiredToken` errors —
usually after a refresh failure that the SDK retried but the app didn't.

**Pod Identity:** ~6 hours by default. The agent absorbs refresh; pods
see steady-state credentials.

---

## What Pod Identity does NOT solve

An honest list. Each item maps to behavior this codebase encodes — Pod
Identity isn't magic, and migrating without understanding the gaps is
worse than not migrating at all.

### Cross-account access

A Pod Identity Association can only point at a role in the *same* account
as the cluster. If you currently use IRSA to assume a role in another
account directly (cluster A's OIDC trusted by role in account B), you
can't migrate that pattern as-is.

The recommended workaround, per [SPEC §8.2](../SPEC.md): create an
intermediate role in the cluster's account that assumes the cross-account
target via `sts:AssumeRole`. Migrate the intermediate to Pod Identity.
The cross-account hop happens between the two roles, not between cluster
and account.

This codebase classifies cross-account trust as **red**
(`CROSS_ACCOUNT_TRUST`) and skips it from auto-migrate plans. You build
the intermediate role separately.

### Apps that read `AWS_WEB_IDENTITY_TOKEN_FILE` directly

The SDK abstracts the credential mechanism; apps that bypass the SDK and
read the token file by hand will break when the path's contents change
audience and purpose under Pod Identity. The classifier emits
`CUSTOM_TOKEN_FILE_PATH` if it sees the env var overridden in pod spec,
but cannot statically detect raw file reads from inside the container.

The remedy: change the app to use the standard SDK credential chain.
Then it works under both IRSA and Pod Identity with no code change.

### Old AWS SDK versions

The container credential provider has been in the AWS SDKs since 2017,
but very old SDKs (pre-`AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE` support)
won't pick up the file-based bearer. Symptom: pod has Pod Identity env
vars set, but `aws sts get-caller-identity` returns the *node's* role —
the SDK fell through to IMDS.

The verify step's
[`verify/probe.py`](../../src/eks_identity_migrator/verify/probe.py) is
designed for this — `--probe` execs `aws sts get-caller-identity` and
checks the returned ARN. If it doesn't match the expected Pod Identity
session, you have an SDK problem, not a migration problem.

### Operator charts (ALB controller, Karpenter, CSI drivers, …)

Each operator has its own chart, its own IAM-config conventions, and its
own Pod Identity migration story. Some support Pod Identity natively in
recent versions; some still default to IRSA annotations; some need
flag changes. This codebase flags well-known operator SAs with the
yellow `OPERATOR_MANAGED` finding plus a per-operator hint string from
[`risk/operators.py`](../../src/eks_identity_migrator/risk/operators.py).

v0.1 explicitly does not auto-migrate operators. Read the operator's
docs first; the Pod Identity statement on the role can be added safely
in advance via this tool's `--strategy append`, but the *cleanup* step
(removing the IRSA annotation) should wait until you're sure the
operator's pod has restarted onto the new credentials.

### Same-cluster `default` SA usage

Pods with empty `spec.serviceAccountName` use the namespace's `default`
SA. If `default` carries the IRSA annotation, every pod in the namespace
with no explicit SA picks it up — possibly far more workloads than you
think. The classifier emits `DEFAULT_SA_ANNOTATED` (yellow) on these
mappings; humans must scope-check before migrating.

---

## A migration mental model

Why does this tool work in three apply phases (`trust → association →
cleanup`) instead of a single toggle? Because the question to ask while
migrating is not *"can this work under Pod Identity?"* but *"is the SDK
in this specific pod actually using it?"* The phases give you separable
checkpoints:

```
                 ┌─────────────────────────────────────────────────────┐
                 │  Phase 1: trust                                     │
                 │  - update IAM trust policy                          │
                 │  - --strategy append → ADD Pod Identity statement   │
                 │      (existing OIDC trust kept verbatim)            │
                 │  - --strategy replace → strip OIDC, keep non-OIDC   │
                 │      principals (e.g. EC2 service principal)        │
                 │                                                     │
                 │  Reversible: journal records the prior trust JSON;  │
                 │  rollback restores it byte-for-byte.                │
                 └────────────────────────┬────────────────────────────┘
                                          │
                                          ▼
                 ┌─────────────────────────────────────────────────────┐
                 │  Phase 2: association                                │
                 │  - require eks-pod-identity-agent addon (preflight)│
                 │  - eks:CreatePodIdentityAssociation                 │
                 │      key: (cluster, ns, sa) → roleArn               │
                 │  - existing matching association → "already-applied"│
                 │  - existing different-role association → ERROR     │
                 │                                                     │
                 │  Reversible: rollback deletes the association.     │
                 │  Pods continue using IRSA env vars until restart.  │
                 └────────────────────────┬────────────────────────────┘
                                          │
                          (bounce / restart pods so the SDK
                           picks the new credential source)
                                          │
                                          ▼
                 ┌─────────────────────────────────────────────────────┐
                 │  GATE: verify                                       │
                 │  - find one running pod per SA                      │
                 │  - inspect env vars                                 │
                 │      AWS_CONTAINER_CREDENTIALS_FULL_URI present?    │
                 │      AWS_WEB_IDENTITY_TOKEN_FILE  still present?    │
                 │  - DUAL state during append migration is normal     │
                 │      until SA annotation is removed in Phase 3      │
                 │  - --probe: also exec `aws sts get-caller-identity` │
                 │                                                     │
                 │  No mutation. Read-only. Run as often as you like.  │
                 └────────────────────────┬────────────────────────────┘
                                          │
                                          ▼
                 ┌─────────────────────────────────────────────────────┐
                 │  Phase 3: cleanup                                   │
                 │  - remove SA annotation eks.amazonaws.com/role-arn  │
                 │  - optionally (--remove-oidc-trust):                │
                 │      drop OIDC statements from the trust policy    │
                 │                                                     │
                 │  Only run after verify confirms the SDK has        │
                 │  switched. Once cleanup is done, IRSA is gone.     │
                 └─────────────────────────────────────────────────────┘
```

The whole sequence is journaled to NDJSON
([`journal/`](../../src/eks_identity_migrator/journal/), schema in
[SPEC §9](../SPEC.md)), and every operation has a known inverse. Rollback
walks the journal in reverse and undoes each entry — see
[SPEC §7.6](../SPEC.md).

The mental model in one sentence:

> **Add the new path while the old still works, switch the SDK to it,
> verify, then remove the old path** — never both at once, never on
> faith.

---

## Where to go from here

- If you want to *run* the tool against a cluster: see the top-level
  [README.md](../../README.md) for install + quickstart, then
  [SPEC §3](../SPEC.md) for the workflow.
- If you want to *contribute*: see [CLAUDE.md](../../CLAUDE.md) for the
  layout, conventions, and the verification gate.
- If you want to dig into AWS's own docs:
  - [EKS Pod Identity user guide](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
  - [Pod Identity Agent setup](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-agent-setup.html)
  - [How EKS Pod Identity works](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-how-it-works.html)
  - [IRSA user guide](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
  - [Confused-deputy prevention with `aws:SourceAccount` / `aws:SourceArn`](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)
- If you want to *audit* without migrating: [Datadog
  MKAT](https://github.com/DataDog/managed-kubernetes-auditing-toolkit) is
  the best read-only option.
