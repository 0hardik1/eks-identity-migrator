# How EKS Pod Identity works

> **What you'll get from reading this:** the shape of EKS Pod Identity from
> the IAM trust shape down to the local HTTP endpoint the agent serves on
> every node, plus the operational lifecycle (addon → association → pod
> restart → credential refresh) and the limits the design imposes.

[EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
was [announced at re:Invent 2023](https://aws.amazon.com/blogs/aws/amazon-eks-pod-identity-simplifies-iam-permissions-for-applications-on-amazon-eks-clusters/)
as the AWS-recommended way to grant AWS permissions to pods on EKS. It is a
*replacement* for IRSA (covered in [01-oidc-and-irsa.md](01-oidc-and-irsa.md)),
not an addition.

If you haven't read the IRSA chapter, the punchline of this one will be
harder to appreciate — Pod Identity is best understood as "what if the
credential dance happened over a local socket on each node, with the cluster
identity instead of a per-pod JWT?". The comparison is in
[03-irsa-vs-pod-identity.md](03-irsa-vs-pod-identity.md).

---

## 1. The shape of Pod Identity in one paragraph

Pod Identity has three moving parts and a fourth that's a logical
consequence of the other three:

1. A **Pod Identity Association** stored in the EKS control plane: a
   mapping from `(cluster, namespace, serviceAccount) → roleArn`.
2. The **`eks-pod-identity-agent`** EKS addon — a daemonset on every node —
   that exposes a local HTTP endpoint on a link-local IP and answers
   credential requests from pods.
3. A **new IAM trust shape** using `pods.eks.amazonaws.com` as a service
   principal, with mandatory confused-deputy conditions on
   `aws:SourceAccount` and `aws:SourceArn`.
4. (Consequence) **No JWT, no OIDC provider, no SA annotation.** The
   credential delivery mechanism is the
   [container credential provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-container-credentials.html),
   which the AWS SDK already supported for ECS.

Each part below.

---

## 2. The Pod Identity Association — the new source of truth

The mapping from "this ServiceAccount" to "that IAM role" lives in the EKS
API as a first-class object:

```
PodIdentityAssociation {
  clusterName       : "my-cluster"
  namespace         : "production"
  serviceAccount    : "app-frontend"
  roleArn           : "arn:aws:iam::123456789012:role/app-frontend"
  associationId     : "a-12345abcdef"
  associationArn    : "arn:aws:eks:...:podidentityassociation/.../a-12345abcdef"
  ...
}
```

You create it via
[`eks:CreatePodIdentityAssociation`](https://docs.aws.amazon.com/eks/latest/APIReference/API_CreatePodIdentityAssociation.html)
and look it up via `eks:ListPodIdentityAssociations`. There is **no
ServiceAccount annotation** — the SA in Kubernetes can be a stock
`metadata-only` object with no special markings. Pod Identity is wired up
on the AWS side, not the K8s side.

This codebase's apply-phase implementation is in
[`apply/association.py`](../../src/eks_identity_migrator/apply/association.py)
— note the idempotency check (`if existing... return already-applied`) and
the conflict path (an existing association pointing at a *different* role
becomes a hard error rather than a silent overwrite, per
[SPEC §7.4](../SPEC.md)).

The mapping key is the triple `(cluster, namespace, serviceAccount)`. One
SA → one role per cluster. There is no wildcard, no glob, no `ForAllValues`.
If twenty SAs in a namespace need the same role, that's twenty associations.

> **Why this matters for migration:** if your IRSA trust policy used
> `WILDCARD_SUB` (`system:serviceaccount:ns:*`), the audit step has to
> enumerate the SAs *currently* annotated with the role and emit one
> Association per SA. New SAs added to the namespace later will **not**
> auto-inherit access — that's a deliberate Pod Identity invariant, not a
> tooling limitation. See [01-oidc-and-irsa.md §7](01-oidc-and-irsa.md#wildcard_sub).

---

## 3. The Pod Identity Agent — the local credential broker

The [`eks-pod-identity-agent`](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-agent-setup.html)
is an EKS-managed addon. Once installed, it runs as a daemonset and serves
HTTP on a link-local address on every node:

```
http://169.254.170.23/v1/credentials       (IPv4)
http://[fd00:ec2::23]/v1/credentials       (IPv6)
```

When a pod is admitted on a node and its ServiceAccount has a Pod Identity
Association, the EKS-managed mutating webhook (different from the IRSA
webhook of yore — same idea, different code path) injects:

| Env var                                      | Value                                                |
|----------------------------------------------|------------------------------------------------------|
| `AWS_CONTAINER_CREDENTIALS_FULL_URI`         | `http://169.254.170.23/v1/credentials` (or IPv6)     |
| `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE`     | path to the SA's bound projected token file         |

The AWS SDK's [container credential
provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-container-credentials.html)
sees these and, instead of doing OIDC dance, makes a plain HTTP `GET` to the
URI with the bearer token from the auth file in the `Authorization` header.

Note that Pod Identity *also* uses a projected ServiceAccount token — but
the audience is **not** `sts.amazonaws.com`, the file is read by the
**agent**, not the SDK, and the agent never returns the JWT to the pod.
The pod sees only the AccessKey/SecretKey/SessionToken triple, exactly as
if it were running on EC2.

```
                        ┌───────────────────────────────────┐
                        │  EKS control plane                 │
                        │   PodIdentityAssociation table     │
                        │     (cluster, ns, sa) → roleArn    │
                        └────────────┬───────────────────────┘
                                     │ agent queries on demand
                                     │
        ┌────────────────────────────┴────────────────────────┐
        │                                                     │
        │   node                                              │
        │  ┌────────────────┐    1. local HTTP                 │
        │  │  Pod           │ ────────────────────▶ 169.254.170.23/v1/credentials
        │  │ $AWS_CONTAINER │       Authorization: Bearer <sa-token>
        │  │   _CREDENTIALS │                                  │
        │  │   _FULL_URI    │ ◀──────────────────── 4. JSON: {AccessKeyId,...}
        │  └───────┬────────┘                                  │
        │          │                                           │
        │  ┌───────▼────────────────────────────────────┐     │
        │  │ eks-pod-identity-agent (daemonset)         │     │
        │  │  - reads bearer token (SA's projected JWT) │     │
        │  │  - calls EKS to validate (cluster,ns,sa)   │     │
        │  │  - calls sts:AssumeRole on the role        │     │
        │  │    pointed at by the association           │     │
        │  └───────┬────────────────────────────────────┘     │
        └──────────┼──────────────────────────────────────────┘
                   │
                   │ 2. EKS validate + sts:AssumeRole + sts:TagSession
                   ▼
        ┌──────────────────────────────────────────────────┐
        │  AWS STS                                         │
        │    Principal:    pods.eks.amazonaws.com           │
        │    Conditions:                                    │
        │      aws:SourceAccount = <cluster account>        │
        │      aws:SourceArn     = <cluster ARN>            │
        │    Session tags applied (eks-cluster-name,        │
        │      kubernetes-namespace, kubernetes-service-    │
        │      account, kubernetes-pod-name, ...-pod-uid)   │
        └──────────────────────┬───────────────────────────┘
                               │ 3. credentials (≈ 6 hours)
                               ▼
                         (returned to agent → pod)
```

Two subtleties:

- The SDK is the same. Old apps that used IRSA need *no* code change to
  switch to Pod Identity, *as long as* they let the SDK's default
  credential chain do its job. Apps that read
  `AWS_WEB_IDENTITY_TOKEN_FILE` directly (the
  [`CUSTOM_TOKEN_FILE_PATH`](../../src/eks_identity_migrator/risk/codes.py)
  finding) need fixing.
- The credential lifetime is **longer** than IRSA's (~6 hours by default
  vs ~1 hour). The agent caches and refreshes; the pod just sees a steady
  stream of valid credentials.

This codebase's `verify` step keys off the env vars to determine which
mechanism a pod is *actually* using:
[`verify/probe.py`](../../src/eks_identity_migrator/verify/probe.py):11–15
defines the env-var sets, and the `_classify_envs` helper distinguishes
`POD_IDENTITY` / `IRSA` / `DUAL` / `FAILED`. The DUAL state shows up
during `--strategy append` migration: both env-var groups are present
(IRSA from the legacy webhook, Pod Identity from the new one); SDK
preference order then decides which one wins.

---

## 4. The new IAM trust shape

Here's the canonical Pod Identity statement this codebase emits. It's the
second statement in the translator's append-output fixture
[`testdata/translator/t01_append_to_minimal_irsa.out.json`](../../testdata/translator/t01_append_to_minimal_irsa.out.json):17–26:

```json
{
  "Sid": "PodIdentityForappfrontend",
  "Effect": "Allow",
  "Principal": { "Service": "pods.eks.amazonaws.com" },
  "Action": ["sts:AssumeRole", "sts:TagSession"],
  "Condition": {
    "StringEquals": { "aws:SourceAccount": "123456789012" },
    "ArnEquals":     { "aws:SourceArn":     "arn:aws:eks:us-west-2:123456789012:cluster/my-cluster" }
  }
}
```

```
┌──────────────────────────────────────────────────────────────────────┐
│  Pod Identity trust statement — anatomy                              │
├──────────────────────────────────────────────────────────────────────┤
│  Principal.Service: pods.eks.amazonaws.com                           │
│      └── one service principal, account-wide.                        │
│          Replaces N OIDC provider ARNs (one per cluster).            │
│                                                                       │
│  Action: ["sts:AssumeRole", "sts:TagSession"]                         │
│      └── AssumeRole — the standard role-assumption API                │
│      └── TagSession — required because EKS injects session tags       │
│                                                                       │
│  Condition.StringEquals "aws:SourceAccount"                           │
│      └── the cluster's account ID — confused-deputy guard             │
│                                                                       │
│  Condition.ArnEquals "aws:SourceArn"                                  │
│      └── the cluster ARN — narrows the trust to ONE cluster          │
│                                                                       │
│  Sid (optional, this codebase generates one)                          │
│      └── "PodIdentityFor<alnum-of-sa-name>", first 32 chars           │
└──────────────────────────────────────────────────────────────────────┘
```

A few things to notice:

- **Principal is a service principal**, not a federated principal. AWS
  itself vouches for the Pod Identity service; you no longer have to
  register a per-cluster OIDC provider.
- **Both `aws:SourceAccount` and `aws:SourceArn` are mandatory** in this
  codebase. They are emitted by
  [`policy/translator.py`](../../src/eks_identity_migrator/policy/translator.py):44–47
  and the requirement is called out in [SPEC §7.3](../SPEC.md). Skipping
  these conditions creates a [confused-deputy
  vulnerability](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html):
  *any* EKS cluster's pod-identity service in your account could assume
  the role.
- **`sts:TagSession` is in the action list** because EKS injects session
  tags on every assumption (next section). Without it the assume call
  fails with `AccessDenied`.
- **`Sid` is generated** by this codebase as `PodIdentityFor<alnum-of-sa>`
  truncated to 32 chars, so re-running the translator on the same input
  yields stable JSON for diffs (deterministic plans, [SPEC §12.2](../SPEC.md)).

### Session tags injected by EKS

When the agent calls `sts:AssumeRole` it includes these
[session tags](https://docs.aws.amazon.com/STS/latest/APIReference/API_TagSession.html)
on every assumption:

| Tag key                            | Value                                        |
|------------------------------------|----------------------------------------------|
| `eks-cluster-name`                 | the cluster name                             |
| `eks-cluster-arn`                  | the full cluster ARN                         |
| `kubernetes-namespace`             | the pod's namespace                          |
| `kubernetes-service-account`       | the SA name                                  |
| `kubernetes-pod-name`              | the pod's name                               |
| `kubernetes-pod-uid`               | the pod's UID                                |

Combined with [aws:PrincipalTag /
aws:RequestTag](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_iam-condition-keys.html)
on the *target* role's permission policies, this makes ABAC patterns
straightforward — e.g., scope a single role to write only to S3 prefixes
that match `${aws:PrincipalTag/kubernetes-namespace}`.

If a pre-existing trust policy already contains `sts:TagSession` (some
hand-written IRSA policies do, in case session tagging was needed),
the classifier emits the informational `STS_TAGSESSION_PRESENT` finding
and the translator de-duplicates rather than emitting it twice. Fixture:
[`15_tagsession_already_present.in.json`](../../testdata/trust-policies/15_tagsession_already_present.in.json).

---

## 5. The full credential flow, end-to-end

Putting agent + association + trust shape together:

```
┌────────────────────────────────────────────────────────────────────┐
│  0. Pre-flight (one-time):                                         │
│     ├─ install eks-pod-identity-agent addon                        │
│     │     (this codebase fails apply --phase association if it's   │
│     │      missing → POD_IDENTITY_AGENT_MISSING)                   │
│     ├─ create Pod Identity Association                              │
│     │     (cluster, namespace, sa) → roleArn                       │
│     └─ ensure role's trust policy has the Pod Identity statement   │
└────────────────────────────────────────────────────────────────────┘

   1. Pod admitted, mutating webhook injects env vars:
      $AWS_CONTAINER_CREDENTIALS_FULL_URI
      $AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE

   2. App makes an AWS SDK call — SDK credential chain picks the
      ContainerCredentialsProvider, reads the auth token file, GETs
      the URI with `Authorization: Bearer <token>`.

   3. Agent on this node:
      a. Reads the bearer (a projected SA token, signed by the
         cluster API server).
      b. Calls EKS to validate that the (cluster, ns, sa) tuple has
         a Pod Identity Association.
      c. On match, calls sts:AssumeRole + sts:TagSession on the
         associated role with cluster ARN as aws:SourceArn.

   4. STS evaluates:
      - Principal.Service == pods.eks.amazonaws.com  ✓
      - aws:SourceAccount matches StringEquals condition  ✓
      - aws:SourceArn matches ArnEquals condition         ✓
      - Session tags applied.

   5. STS returns ~6h temporary credentials → agent → pod.

   6. SDK caches; agent refreshes when near expiry. Pod is unaware
      of the renewal — credential lifetime is invisible above the
      SDK layer.
```

---

## 6. Lifecycle: install, associate, restart, refresh

### Install (once per cluster)

The `eks-pod-identity-agent` is a managed [EKS addon](https://docs.aws.amazon.com/eks/latest/userguide/eks-add-ons.html).
You install it via console, CLI, or IaC like any other addon. This
codebase's apply phase **refuses to create associations** if the addon is
missing — see
[`apply/association.py`](../../src/eks_identity_migrator/apply/association.py):17–23
(`preflight_addon` raises `PodIdentityAgentMissingError`) and the
finding code `POD_IDENTITY_AGENT_MISSING`. Without the agent, associations
exist in the EKS control plane but no env vars are injected — pods see
nothing change.

### Create / update / delete associations

`eks:CreatePodIdentityAssociation` is idempotent in the same sense as
this tool: re-running with the same `(cluster, ns, sa, roleArn)` is fine,
but trying to associate the *same* SA with a *different* role is a hard
error you must resolve manually — see
[`apply/association.py:42-51`](../../src/eks_identity_migrator/apply/association.py).
Updates use `eks:UpdatePodIdentityAssociation`; deletes use
`eks:DeletePodIdentityAssociation` and that's exactly what the rollback
phase does (see [SPEC §7.6](../SPEC.md)).

### Pod restart

Existing pods don't pick up env-var changes — the webhook injects them at
admission time. After creating an association you must **restart the
pod** (or wait for natural rollover) for it to start using Pod Identity
credentials. SPEC §3 calls this out explicitly in the workflow ("Bounce
or restart pods so SDK picks up new credential source").

In a `--strategy append` migration this is a deliberate quiet period: the
pod is still running on IRSA env vars (from the legacy webhook) until
restart. After restart, both env-var sets are present on the new pod (the
new agent's webhook injects Pod Identity envs; the legacy IRSA webhook
*also* still injects, because the SA is still annotated). The SDK's
[credential provider chain
order](https://docs.aws.amazon.com/sdkref/latest/guide/standardized-credentials.html#credentialProviderChain)
decides which wins — recent SDK versions prefer Pod Identity. The verify
step
([`verify/probe.py`](../../src/eks_identity_migrator/verify/probe.py))
detects the `DUAL` state explicitly so you can confirm the SDK is
actually picking the new path.

### Credential refresh

Within a pod the SDK refreshes credentials transparently. The agent does
the actual STS call, caches the result, and re-issues to subsequent pods
on the same node within the cache window. Token rotation for the bearer
is handled by the kubelet via
[BoundServiceAccountTokenVolume](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/#bound-service-account-token-volume),
exactly as for IRSA — the bearer is short-lived; the AWS credentials it
exchanges for live longer.

---

## 7. Limits and edges

The honest list of what Pod Identity *can't* do or makes *harder*. Each
maps to behavior this codebase encodes:

### Same-account only

A Pod Identity Association can only point at a role in the same account
as the cluster. If your role lives in a different account, you can't
migrate directly. The classifier marks these red
(`CROSS_ACCOUNT_TRUST` — see
[`02_cross_account_trust.in.json`](../../testdata/trust-policies/02_cross_account_trust.in.json))
and skips them.

The recommended workaround, documented in [SPEC §8.2](../SPEC.md): create
an intermediate role in the cluster's account that assumes the
cross-account target via `sts:AssumeRole`. Migrate the intermediate role
to Pod Identity. The cross-account hop happens between roles, not
between cluster and account.

### Session-name length (64 chars)

IAM caps role session names at 64 characters
([`role_session_name` in IAM
docs](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_terms-and-concepts.html)).
The Pod Identity session-name format encodes cluster, namespace, and SA;
deeply nested namespaces or very long SA names overflow. The check is in
[`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py):139–145
(`_session_name_would_truncate`); the limit constant
`POD_IDENTITY_SESSION_NAME_MAX = 64` lives at line 29. Finding code:
`SESSION_NAME_TOO_LONG`. Fixture:
[`13_session_name_too_long.in.json`](../../testdata/trust-policies/13_session_name_too_long.in.json).

The remedy is renaming — the SA, the namespace, or both. There's no IAM
config that raises the cap.

### Roles also used as instance profiles

Some operator stacks use the *same* role as both an EC2 instance profile
*and* an IRSA target. Trust policy looks like:

```json
{
  "Statement": [
    { "Principal": { "Service": "ec2.amazonaws.com" }, ... },
    { "Principal": { "Federated": "arn:.../oidc-provider/..." }, ... }
  ]
}
```

`--strategy append` is fine: the EC2 statement keeps working, the
Federated statement keeps working, and the Pod Identity statement is
added next to them. `--strategy replace` is dangerous if you're not
careful — but this codebase's translator only strips OIDC IRSA statements
(`_is_oidc_irsa_statement`) and explicitly preserves the EC2 service
principal — see
[`policy/translator.py:113-115`](../../src/eks_identity_migrator/policy/translator.py).
Finding code: `MIXED_PRINCIPAL_EC2`. Fixture:
[`14_mixed_ec2_irsa.in.json`](../../testdata/trust-policies/14_mixed_ec2_irsa.in.json).

### Cluster operators (ALB controller, Karpenter, CSI, …)

Pod Identity works fine for operators in principle, but each operator
ships its own IAM-config story (Helm chart values, controller flags,
upstream defaults). Some bake the IRSA annotation in by default; some
support Pod Identity natively in recent versions only. This codebase
flags well-known operator SAs with the yellow `OPERATOR_MANAGED` finding
and a per-operator hint string; see
[`risk/operators.py`](../../src/eks_identity_migrator/risk/operators.py)
for the registry. v0.1 doesn't auto-migrate operators — check the
operator's docs first.

### Old AWS SDK versions

The container credential provider has been in the AWS SDKs since 2017
(introduced for ECS), but very old SDK versions don't know about
`AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE` (the file-based variant). If a
pod is stuck on a 2018-vintage SDK, Pod Identity env vars are present
but the SDK ignores them and falls back to IMDS — which gives the *node's*
role, not the pod's. The verify step's
`VERIFY_STILL_IRSA` outcome catches the easy version of this bug; an SDK
that ignores both env-var sets and silently uses IMDS is harder and
needs a real probe (`verify --probe` runs `aws sts get-caller-identity`
inside the pod).

### Apps that read the JWT directly

Apps that pop open `/var/run/secrets/eks.amazonaws.com/serviceaccount/token`
to inspect the JWT — for ABAC-style claim extraction, or to forward the
JWT to a non-AWS service — break under Pod Identity. The token at that
path is now an internal artifact of the agent's auth, with a different
audience. The classifier emits `CUSTOM_TOKEN_FILE_PATH` if it sees the
override env var on the pod, but it cannot statically detect raw file
reads from inside the container. Humans verify by inspection or by
watching the verify step's output.

---

## 8. Putting it all together

A pod calling AWS under Pod Identity, in one paragraph:

> The kubelet projects a short-lived JWT into the pod (audience: the
> Pod Identity service, not STS). The Pod Identity webhook injects two
> env vars: `AWS_CONTAINER_CREDENTIALS_FULL_URI` pointing at
> `169.254.170.23` and `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE`
> pointing at the projected token. The AWS SDK's
> ContainerCredentialsProvider sees these, GETs the URI with the token as
> a bearer. The `eks-pod-identity-agent` daemonset on the node receives
> the request, validates the (cluster, namespace, serviceAccount) tuple
> against the EKS API's Pod Identity Association table, then calls
> `sts:AssumeRole` + `sts:TagSession` on the associated role using
> `pods.eks.amazonaws.com` as the principal and the cluster ARN as
> `aws:SourceArn`. STS evaluates the trust policy — verifying the
> service principal, the source-account/source-arn conditions, and
> applying the standard EKS session tags — then returns ~6h credentials.
> The agent passes them to the pod over the local HTTP socket; the SDK
> caches; the agent refreshes.

No per-cluster OIDC provider, no SA annotation, no JWT in the SDK
credential path, no public JWKS endpoint dependency, and a confused-deputy
guard on every trust statement by construction.

**Next:** [03-irsa-vs-pod-identity.md](03-irsa-vs-pod-identity.md) —
side-by-side comparison and the migration mental model.
