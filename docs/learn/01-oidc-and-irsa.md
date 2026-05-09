# How OIDC works with IRSA

> **What you'll get from reading this:** a complete, mechanism-by-mechanism
> picture of how a pod ends up holding short-lived AWS credentials in the
> IRSA model — from the JWT the kubelet projects into the pod, all the way to
> the IAM trust policy STS evaluates when the SDK calls
> `sts:AssumeRoleWithWebIdentity`.

IRSA — **IAM Roles for Service Accounts** — is the way EKS clusters granted
AWS permissions to pods from 2019 until EKS Pod Identity arrived in late
2023. It's still extremely common. It works by turning each EKS cluster into
an OpenID Connect (OIDC) identity provider that AWS STS already knows how to
trust.

To follow along you need to understand four moving parts in order:

1. OIDC itself — the standard.
2. EKS as an OIDC issuer.
3. The projected ServiceAccount token (a JWT).
4. The IAM role's trust policy that ties it all together.

Then we look at the full credential flow as one diagram, and finally at all
the ways this design leaks — every leak corresponds to one of the finding
codes in
[`risk/codes.py`](../../src/eks_identity_migrator/risk/codes.py).

---

## 1. OIDC, in one page

[OpenID Connect 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
is an identity layer built on top of OAuth 2.0. The piece relevant to IRSA
is the **ID token**: a [JWT (RFC 7519)](https://www.rfc-editor.org/rfc/rfc7519)
issued by an *OIDC provider* (the **issuer**) that asserts who the bearer is.

Every OIDC issuer is identified by a URL (the issuer URL) and publishes:

- A **discovery document** at `<issuer>/.well-known/openid-configuration`
  describing the issuer's capabilities and pointing to its keys.
- A **JWKS endpoint** ([RFC 7517 — JSON Web Key](https://www.rfc-editor.org/rfc/rfc7517))
  publishing the *public* halves of the keys it uses to sign tokens.

A *relying party* (here, AWS STS) verifies an ID token by:

```
        ┌────────────────────┐
        │  ID token (JWT)    │  signed by issuer's private key
        └─────────┬──────────┘
                  │
                  ▼
   1. fetch <issuer>/.well-known/openid-configuration
   2. follow `jwks_uri` → fetch JWKS (public keys)
   3. verify the JWT's signature with the matching `kid`
   4. check claims:
        iss == expected issuer
        aud matches expected audience
        exp not yet passed
        sub identifies the right subject
```

A JWT itself is three base64url-encoded parts joined with `.`:

```
<header>.<payload>.<signature>
```

The payload is JSON — a **claim set**. The four claims that matter for IRSA
are:

| Claim | Meaning                                                |
|-------|--------------------------------------------------------|
| `iss` | Issuer URL — must equal the OIDC provider's URL.       |
| `sub` | Subject — *who* this token is about.                   |
| `aud` | Audience — *who* this token is intended for.           |
| `exp` | Expiration time (Unix timestamp).                      |

Hold onto those four — they're the lever IRSA pulls.

---

## 2. EKS as an OIDC issuer

When you create an EKS cluster, AWS provisions an OIDC issuer URL of the form

```
https://oidc.eks.<region>.amazonaws.com/id/<unique-cluster-id>
```

The cluster's API server signs ServiceAccount tokens with a key pair whose
public half is published at the issuer's JWKS endpoint. So far this is
plumbing — Kubernetes can do this on its own.

What makes it *AWS-aware* is one extra step: you register that issuer in IAM
as an **OIDC identity provider**. After registration, AWS has a record like:

```
IAM > Identity Providers > OpenID Connect
  └─ arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE
```

That ARN is the trust anchor for everything that follows. STS will only
accept tokens whose `iss` matches a registered OIDC provider in your account.

> Concretely: this codebase classifies a role as **gray /
> `FOREIGN_OIDC_ISSUER`** when its trust policy lists an OIDC provider that
> doesn't match the cluster being audited. See
> [`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py) —
> `_no_oidc_issuer_matches_cluster`.

This registration is **per cluster**. Ten clusters means ten OIDC providers
in IAM, and roles you want to share across clusters need every issuer's ARN
in their trust policy. Hold that thought; it's the first IRSA pain point.

---

## 3. The projected ServiceAccount token

When a pod is admitted, the kubelet projects a short-lived JWT into a
well-known path inside the pod's filesystem:

```
/var/run/secrets/eks.amazonaws.com/serviceaccount/token
```

(The path is the IRSA convention. Vanilla Kubernetes uses
`/var/run/secrets/kubernetes.io/serviceaccount/token` for cluster-internal
auth — these are different files.)

A decoded sample IRSA token (header omitted) looks roughly like this — every
field is significant:

```json
{
  "iss": "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE",
  "sub": "system:serviceaccount:production:app-frontend",
  "aud": ["sts.amazonaws.com"],
  "exp": 1715284800,
  "iat": 1715281200,
  "kubernetes.io": {
    "namespace": "production",
    "serviceaccount": {
      "name": "app-frontend",
      "uid": "..."
    },
    "pod": { "name": "app-frontend-7c4fcb-xkwwl", "uid": "..." }
  }
}
```

Read carefully:

- `iss` is the cluster's issuer URL.
- `sub` is **`system:serviceaccount:<namespace>:<service-account>`** — that's
  the canonical Kubernetes-formatted identity for a ServiceAccount.
- `aud` defaults to `sts.amazonaws.com` for IRSA tokens — STS expects to see
  itself as the audience.
- `exp` is an hour by default. The kubelet rotates the token automatically
  via [BoundServiceAccountTokenVolume](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/#bound-service-account-token-volume).

Compare those `aud` and `sub` values to the canonical IRSA trust-policy
fixture in this repo:

```json
{
  "Condition": {
    "StringEquals": {
      "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:aud":
        "sts.amazonaws.com",
      "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub":
        "system:serviceaccount:production:app-frontend"
    }
  }
}
```

— from [`testdata/trust-policies/00a_green_minimum.in.json`](../../testdata/trust-policies/00a_green_minimum.in.json):11–14.

The condition keys are formed by gluing `<issuer-host-path>` to `:aud` /
`:sub`. The values are exactly what's in the JWT. STS will only assume the
role if both match.

---

## 4. The ServiceAccount annotation and pod-side wiring

You don't write a Pod manifest with role ARNs in it. Instead, you annotate
the **ServiceAccount**:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-frontend
  namespace: production
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/app-frontend
```

The EKS pod-identity webhook (the *original* mutating webhook from 2019 — not
to be confused with the new Pod Identity *agent* covered in
[02-pod-identity.md](02-pod-identity.md)) sees the annotation at admission
time and mutates the pod spec to inject:

| Env var                         | Value                                                                |
|---------------------------------|----------------------------------------------------------------------|
| `AWS_ROLE_ARN`                  | the role ARN from the annotation                                     |
| `AWS_WEB_IDENTITY_TOKEN_FILE`   | `/var/run/secrets/eks.amazonaws.com/serviceaccount/token`            |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | best-effort default                                              |

Plus a projected-volume mount so the token file actually exists at that
path. The AWS SDK's [default credential provider
chain](https://docs.aws.amazon.com/sdkref/latest/guide/standardized-credentials.html)
checks for these env vars; if both are set, it uses the
**WebIdentityTokenFileCredentialsProvider** which calls
`sts:AssumeRoleWithWebIdentity` for you with the token file's contents as the
`WebIdentityToken` parameter.

> **Why this codebase cares:** if an app overrides
> `AWS_WEB_IDENTITY_TOKEN_FILE` to a custom path (e.g. it does its own token
> rotation, or reads the JWT directly to extract claims), the predicate
> `_has_custom_token_file_path` in
> [`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py) emits the
> `CUSTOM_TOKEN_FILE_PATH` finding. After Pod Identity migration that env
> var stops being meaningful, but the app still expects it. Humans must fix
> the app — the tool can't.

---

## 5. The IAM trust policy, line by line

Here is the smallest possible trust policy that allows IRSA — straight from
the green-minimum fixture
[`testdata/trust-policies/00a_green_minimum.in.json`](../../testdata/trust-policies/00a_green_minimum.in.json):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:aud": "sts.amazonaws.com",
          "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub": "system:serviceaccount:production:app-frontend"
        }
      }
    }
  ]
}
```

```
┌─────────────────────────────────────────────────────────────────────┐
│  IRSA trust policy — anatomy                                        │
├─────────────────────────────────────────────────────────────────────┤
│  Principal.Federated                                                 │
│      └── ARN of the IAM OIDC provider (one per cluster)             │
│          must match an `iss` registered in this account             │
│                                                                      │
│  Action: sts:AssumeRoleWithWebIdentity                               │
│      └── this is THE STS API for OIDC JWTs                           │
│                                                                      │
│  Condition keys                                                      │
│      <issuer-host-path>:aud  =  sts.amazonaws.com                    │
│      <issuer-host-path>:sub  =  system:serviceaccount:<ns>:<sa>      │
│                                                                      │
│      The host-path prefix is how STS scopes claim conditions to a   │
│      specific issuer — same role can list multiple issuer prefixes  │
│      (multi-cluster role reuse).                                    │
└─────────────────────────────────────────────────────────────────────┘
```

A few subtleties that matter when classifying real-world policies:

- `Principal.Federated` may be a **string or an array**. Both shapes are
  legal IAM JSON; the parser in
  [`policy/parser.py`](../../src/eks_identity_migrator/policy/parser.py)
  normalizes them. Fixture
  [`00f_principal_federated_array.in.json`](../../testdata/trust-policies/00f_principal_federated_array.in.json)
  exercises the array form.
- A role's trust policy may have **multiple statements**, each granting a
  different issuer or a different SA, or even a non-OIDC principal like
  `ec2.amazonaws.com`. The classifier handles each of these cases via
  separate finding codes (`MULTI_STATEMENT_OIDC`, `MIXED_PRINCIPAL_EC2`,
  …).
- `Condition` may use `StringLike` instead of `StringEquals` — a wildcard
  `sub`. That's a deliberate IRSA pattern for sharing one role across many
  SAs in a namespace, and it's the source of the `WILDCARD_SUB` finding.
- `Condition` may use
  [`ForAllValues:StringEquals`](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-single-vs-multi-valued-context-keys.html)
  with a list of subjects — a deliberate "this role is shared by these N
  SAs" pattern, surfaced as `MULTI_SUB_FORALL`.

---

## 6. The full credential flow

```
                                                       ┌───────────────────┐
                                                       │  IAM OIDC         │
                                                       │  Provider record  │
                                                       │  (per cluster,    │
                                                       │   per account)    │
                                                       └────────┬──────────┘
                                                                │ trust anchor
                                                                ▼
┌──────────┐   1. project token     ┌──────────────────────────────────────┐
│  kubelet │ ─────────────────────▶ │  Pod                                 │
│          │                        │   /var/run/.../token (signed JWT)    │
│          │   inject env vars      │   $AWS_ROLE_ARN                      │
│          │ ─────────────────────▶ │   $AWS_WEB_IDENTITY_TOKEN_FILE       │
└──────────┘   (via mutating wh)    └──────────────┬───────────────────────┘
                                                   │
                                                   │ 2. SDK reads env + token
                                                   │
                                                   ▼
                                ┌───────────────────────────────────────┐
                                │  sts:AssumeRoleWithWebIdentity         │
                                │     RoleArn          = $AWS_ROLE_ARN  │
                                │     WebIdentityToken = <JWT>          │
                                └──────────────┬────────────────────────┘
                                               │ 3. STS validates
                                               ▼
                                ┌───────────────────────────────────────┐
                                │  AWS STS                              │
                                │   - GET <iss>/.well-known/openid-     │
                                │         configuration → jwks_uri      │
                                │   - GET <jwks_uri> → fetch public keys│
                                │   - verify JWT signature              │
                                │   - check exp                         │
                                │   - evaluate role trust policy:       │
                                │       Principal.Federated matches     │
                                │       <issuer>:aud  matches condition │
                                │       <issuer>:sub  matches condition │
                                └──────────────┬────────────────────────┘
                                               │ 4. on success
                                               ▼
                                ┌───────────────────────────────────────┐
                                │  Temporary credentials                │
                                │   AccessKeyId / SecretAccessKey /     │
                                │   SessionToken (≈ 1 hour TTL)         │
                                └──────────────┬────────────────────────┘
                                               │ 5. SDK caches; refreshes
                                               ▼
                                            (your AWS SDK calls)
```

Two things to internalize from this diagram:

- **STS reaches out to your cluster's OIDC issuer.** The issuer URL must be
  reachable from AWS. EKS's managed issuer is reachable by default; for
  self-managed Kubernetes, the issuer endpoint has to live somewhere AWS can
  GET it.
- **The JWT is the only proof the pod is who it says.** The trust policy's
  conditions on `aud`/`sub` are the only thing standing between this role
  and *any other* SA the same cluster might mint a token for.

---

## 7. What can go wrong (the reason this tool exists)

Every leak in the IRSA design corresponds to a finding code defined in
[`risk/codes.py`](../../src/eks_identity_migrator/risk/codes.py) and a
predicate in
[`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py). Each is
worth knowing on its own:

### `ROLE_USED_BY_MULTIPLE_CLUSTERS`

Same role's trust policy lists OIDC providers from clusters A and B. Useful
because you can promote the same workload from staging to prod without
touching IAM — but it means every trust-policy edit you make for cluster A
is one bad copy-paste away from breaking cluster B.

This codebase's `--strategy append` (default) preserves all OIDC
statements, so adding Pod Identity to a multi-cluster role is safe.
`--strategy replace` would rip cluster B's trust out — the classifier
emits `ROLE_USED_BY_MULTIPLE_CLUSTERS` (yellow) so the plan generator can
gate it. Predicate: `_has_other_oidc_issuer`.

### `CROSS_ACCOUNT_TRUST`

A role in account 222 trusts an OIDC issuer in account 111. Possible with
IRSA — set up the OIDC provider in account 222 pointing at cluster A's
issuer, then add account-111 trust. This pattern is impossible to
replicate with Pod Identity, which is **same-account only**. Marked red.

The fixture
[`02_cross_account_trust.in.json`](../../testdata/trust-policies/02_cross_account_trust.in.json)
shows the shape; the predicate `_has_cross_account_principal` flags it.
The recommended workaround is documented in
[SPEC §8.2](../SPEC.md): create an intermediate role in the cluster's
account that assumes the cross-account target, then migrate the
intermediate.

### `WILDCARD_SUB`

`Condition.StringLike` with `system:serviceaccount:production:*` — every SA
in a namespace shares the role. Convenient, but:

- you can't see which SAs are *actually* using the role without auditing
  pods,
- a future SA created in that namespace silently inherits the role,
- a Pod Identity equivalent doesn't exist (associations are explicit
  `(cluster, ns, sa)` triples).

The audit step lists the SAs *currently* annotated with the role and emits
one Pod Identity Association per SA. Fixture:
[`03_wildcard_sub.in.json`](../../testdata/trust-policies/03_wildcard_sub.in.json).

### `MULTI_SUB_FORALL`

`Condition.ForAllValues:StringEquals` listing several SAs explicitly. Same
remediation as `WILDCARD_SUB` — one Association per listed SA. Fixture:
[`04_forall_multi_sub.in.json`](../../testdata/trust-policies/04_forall_multi_sub.in.json).

### `CUSTOM_AUD_CLAIM`

`aud` is anything other than `sts.amazonaws.com`. This means the
ServiceAccount has a custom-audience projected token (configured via the
pod's `serviceAccountToken` projected volume) and is doing something
non-standard — probably acting as an OIDC client to a non-AWS service.
Pod Identity has no equivalent: the agent's token contract is internal.
Marked red. Fixture:
[`05_custom_aud_claim.in.json`](../../testdata/trust-policies/05_custom_aud_claim.in.json).

### `STALE_ANNOTATION`

The SA carries `eks.amazonaws.com/role-arn` but no pod actually uses the
SA. The migration tool refuses to act on it (gray) — there's no pod to
verify against, and removing the annotation might break a CronJob that
fires once a week. Investigate first.

### `DEFAULT_SA_ANNOTATED`

The annotation is on the namespace's `default` SA. Every pod with empty
`spec.serviceAccountName` picks this up — likely far more workloads than
you think. Fixture:
[`08_default_sa_annotated.in.json`](../../testdata/trust-policies/08_default_sa_annotated.in.json).

### `CUSTOM_TOKEN_FILE_PATH`

The pod sets `AWS_WEB_IDENTITY_TOKEN_FILE` to a non-default path — usually
because the app reads the token directly. This breaks under Pod Identity
since the token mechanism is gone entirely. Cannot be statically detected
beyond noticing the env-var override; humans must verify and fix the app.

### `PERMISSION_BOUNDARY` (informational)

The role has an [IAM permission
boundary](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html)
attached. Permission boundaries are unaffected by trust-policy changes —
this is informational only — but if your boundary scopes the role's
permissions to specific tags, double-check that ABAC works the same after
migration (Pod Identity injects different session tags; see
[02-pod-identity.md](02-pod-identity.md)).

### `MIXED_PRINCIPAL_EC2`

The same role is used as an EC2 instance profile *and* as an IRSA target.
Append works fine; replace would strip the IRSA statement(s) but must
preserve the EC2 service principal. The translator's replace path
(`policy/translator.py:113-115`) implements exactly this preservation;
fixture [`14_mixed_ec2_irsa.in.json`](../../testdata/trust-policies/14_mixed_ec2_irsa.in.json)
exercises it.

---

## 8. Operational sharp edges

A handful of IRSA's day-two pain points that don't show up in a single
trust policy but bite operators at scale:

- **One IAM OIDC provider per cluster.** Five clusters, five identity
  providers, five issuer URLs to keep in trust policies. Roles reused
  across clusters end up with stacks of statements; cleanup is manual.
- **Issuer URLs are part of the IAM blast radius.** Compromising one
  cluster's signing key doesn't compromise the others, but you do need a
  per-cluster rotation story. EKS handles this for you, but the IAM
  records (and any policies referencing them) must be cleaned up when a
  cluster is deleted.
- **JWKS reachability.** STS must be able to fetch JWKS for the issuer.
  EKS's default issuer is public; air-gapped clusters need extra plumbing.
- **Token TTL and SDK refresh.** The kubelet rotates the projected token,
  and the SDK re-reads the file when the cached AWS credentials are
  ~5 minutes from expiring. Apps that cache the JWT in memory rather than
  re-reading the file end up making `AssumeRoleWithWebIdentity` calls
  with stale tokens — a subtle bug only visible in the SDK retry/error
  logs.
- **Deeply nested namespaces hit IAM limits.** The session name STS
  generates includes the SA name; very long names truncate. With Pod
  Identity the limit is more visible because the cluster, namespace, and
  SA name all contribute — see
  [`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py)
  predicate `_session_name_would_truncate` and finding
  `SESSION_NAME_TOO_LONG`.

---

## 9. Putting it all together

A pod calling AWS under IRSA, in one paragraph:

> The kubelet projects a short-lived JWT signed by the cluster's API
> server into the pod, and the EKS mutating webhook injects two env vars
> pointing at it. The AWS SDK reads the env vars, picks the
> WebIdentityTokenFileCredentialsProvider, and calls
> `sts:AssumeRoleWithWebIdentity` with the JWT. STS fetches the cluster's
> JWKS, verifies the signature, then evaluates the target role's trust
> policy: it checks that the issuer is registered in this account, that
> `<issuer>:aud == "sts.amazonaws.com"`, and that
> `<issuer>:sub == "system:serviceaccount:<ns>:<sa>"`. If everything
> matches, STS returns hour-long credentials. The SDK caches them and
> refreshes by re-reading the (rotated) token file when they're near
> expiry.

Every IRSA-related finding code in this codebase is a leak in some part of
that paragraph. Pod Identity rebuilds the same workflow with the leaks
plugged.

**Next:** [02-pod-identity.md](02-pod-identity.md) — how Pod Identity
actually works.
