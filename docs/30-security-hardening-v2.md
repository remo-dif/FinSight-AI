# Security Hardening V2 and deployment documentation alignment

Date: 2026-10-31. Branch: `feature/security-hardening-v2`. Base: `67a83c8` (`origin/master`, PR #10). The base already contained Case Workflow V2 and PR #9's `ruff format --check .` backend CI gate. The worktree was clean before branch creation. No AWS CLI/API call, authentication, account recovery, provisioning, deployment or paid infrastructure work was performed. The previous AWS account is closed; no currently operational AWS infrastructure is asserted.

## Verified baseline

| Finding | Classification at inspection | Action |
| --- | --- | --- |
| Registration distinguishes new email (201 + user data) from existing email (409) | Confirmed direct enumeration | Uniform 202 acknowledgement; existing accounts unchanged; same bcrypt work on both valid paths |
| Missing/inactive login bypasses password verification | Already fixed | Preserve dummy bcrypt verification and generic 401 |
| bcrypt character/byte mismatch | Already fixed | Preserve 72 UTF-8 byte validation and existing hashes/algorithm |
| Per-IP login throttling absent | Already fixed | Preserve global/IP login budgets and Redis atomic Lua |
| No quota across IPs for a targeted login identifier | Partially mitigated by IP quotas only | Add temporary HMAC identifier quota before password verification |
| Concurrent refresh can consume the same row twice | Already fixed by conditional consumption | Preserve CAS; additionally serialize the whole family |
| Reusing a consumed refresh leaves its successor usable | Confirmed | Persist family, revoke descendants/family on verified replay |
| Logout only revokes the exact submitted row | Confirmed incomplete session closure | Revoke that login family, including descendants of a consumed parent |
| Raw refresh tokens stored in DB | Already fixed | Preserve SHA-256 hashes; no raw token or new secret persistence |
| Arbitrary forwarded header trusted from a direct peer | Already fixed in application | Preserve explicit CIDRs, physical peer and right-to-left parsing |
| Actual CloudFront/ALB/task trust boundary | Infrastructure-dependent / unavailable | Repository-only analysis and local regression tests; no live AWS claim |
| AWS automatic workflow activation | Configuration-dependent operational risk | Previously required explicit enablement but could run on successful master CI if a stale enablement variable remained true; make manual-only while preserving gates |
| README says document Q&A is unavailable | Confirmed stale after PR #8 | Describe authenticated endpoint/UI and exact citation/grounding limits |
| AWS inventory implies active production resources | Confirmed stale | Separate historical architecture, repository design and unavailable operations |

## Threat model and registration contract

Threats covered are remote registration probes, distributed credential attempts against one identifier, replay of a valid stolen refresh token, concurrent rotations/logout, stale ORM state and partial security/audit commits. Compromised signing keys, privileged direct SQL modification, semantic document prompt injection and an adversary continuously exhausting quotas are not claimed solved.

`POST /api/auth/register` now returns HTTP **202** and only:

```json
{"message":"Registration request processed. Sign in with your credentials; existing accounts keep their current password."}
```

The response is identical for an existing or newly created valid email, without user ID, role, cookies or automatic login. A duplicate never changes the existing password/name. Both valid paths execute the configured bcrypt hash operation once; this reduces an obvious cost difference, not a claim of constant-time responses. Input validation remains 422 and omits submitted password/token inputs. Concurrent email enrollment returns the same acknowledgement and persists one account/audit event.

This intentionally replaces the prior 201/UserResponse and duplicate-email 409 contract. The frontend and relevant API tests are updated accordingly; `/me` retains UserResponse. Existing password limits, exact Unicode bytes, algorithm and login errors are unchanged. Third-party clients that relied on the old registration statuses/body must adapt.

**Residual enumeration:** the application still creates accounts without email ownership verification. An attacker can submit a chosen password for an address and then attempt login, distinguishing a newly created account from an existing account with a different password. Database operation timing may also differ. Generic registration is direct-response mitigation, not complete enumeration prevention. Email verification/invitation policy needs a separate product/security cycle; no email service or fake verification flow is introduced here.

## Login quota policy

The existing general quota (20/IP/minute) and login IP quota (10/IP/minute) are unchanged. Both successful and failed admitted requests count; malformed payloads consume IP budgets as before.

A valid login body also consumes `LOGIN_ACCOUNT_RATE_LIMIT_PER_MINUTE` (default **20**, validated 1..1000) before password verification and before opening the endpoint's database session. A domain-separated HMAC-SHA256 of the case-folded validated email supplies a fixed 64-character key identity, using the existing access signing secret as keyed material. Plaintext emails are not stored in quota keys or logs. Case folding applies only to quota identity, not authentication or stored-email semantics. Signing-key rotation changes identifiers and resets this short-lived quota.

The account quota is independent of IP and applies identically whether or not an account exists. Success does not reset it. Redis uses the existing atomic bounded INCR/EXPIRE Lua operation and fixed minute keys; denials do not extend TTL. There are no permanent lock flags, progressively extended lockouts or account database writes. Redis errors fail closed with 503 / Retry-After 1, without a memory fallback; quota exhaustion is 429 / Retry-After 60.

Development memory uses fixed-minute account buckets, separately from the existing sliding IP buckets. It has a hard cap of 4,096 identifiers per app process, cleans expired entries at capacity, and fails closed with 503 if all slots remain active. No await occurs during its read/check/update. It is not a distributed enforcement substitute; production already requires Redis. Multiple processes need the same signing secret/Redis store and reasonably synchronized clocks. Fixed-window boundary bursts and temporary targeted denial under sustained distributed attack remain possible. The existing IP memory map's idle-key retention is not changed by this cycle.

## Refresh families, replay and logout

New `refresh_token_families` rows represent independent logins. Each stored refresh references one family; rotations inherit it. JWT format/signing and token hashes remain unchanged. Independent sessions never share a family merely because they belong to the same user.

Refresh validates JWT type/signature/expiry, persisted token hash, subject/user ownership and family ownership. It locks the family row with PostgreSQL `SELECT ... FOR UPDATE`, refreshes the token row after the lock and checks current revocation/expiry. Conditional single-use consumption remains in place. A legitimate rotation creates at most one successor, updates the parent link and records audit in one transaction. Cookies are set only after commit. Invalid/unpersisted/hash-mismatched tokens cannot revoke another session.

Replay of a valid, unexpired, hash-matching consumed token revokes the family's active descendants and marks the family revoked, atomically with `auth.refresh_reuse`. Then the endpoint returns the existing generic 401. Logout validates the presented token's hash and revokes the same family with `auth.logout`, including when the presented token is a consumed parent. Already revoked or unknown stored tokens retain the existing idempotent logout response behavior where JWT validation succeeds. Independent families remain usable.

Family locking establishes the same lock order for refresh and logout; no process-local lock or external provider call participates. Real PostgreSQL tests synchronize independent sessions before locking. Two simultaneous refreshes produce one 200 and one 401; the second request's replay detection revokes the winner's successor. Logout racing refresh leaves no usable refresh in the target family. This is **strict replay handling**, not a grace window: legitimate multi-tab races can force reauthentication. A client must not retry an old refresh after losing a response; refetch session state or sign in.

Audit call/flush/commit failure rolls back consumption, family revocation, successor insertion and parent linkage. Internal DB failures are not swallowed as successful authentication. Family reuse audit contains only family ID and the existing acting-user ID, not raw tokens, email or password.

**Access tokens:** existing access JWTs are not family-bound and do not query revocation state. They remain valid until expiry (default 30 minutes) while the user is active, even after logout/replay. This branch revokes refresh capability, not already issued bearer/access-cookie tokens. Immediate access revocation, absolute session lifetimes, MFA and recovery are separate designs. Consumed token records must remain available at least through their JWT expiry to support hash-verified replay detection; no cleanup/retention job is introduced.

## Migration and compatibility

Migration `20261031_0007` adds the family table, indexes and a non-null token family foreign key. A temporary recursive mapping follows existing `replaced_by_jti` chains from their roots, preserving token IDs, JTIs, hashes, expiries, revocation timestamps and successor links. Root token IDs become stable backfilled family IDs; ordinary new logins use independently generated family UUIDs. Previously logged-out terminal chains seed revoked families.

The recursive mapping uses UNION rather than UNION ALL. It rejects incomplete/ambiguous mappings (including cycles, merged-root or cross-user chains) and rolls back the migration rather than guessing. A populated PostgreSQL test proves existing active raw JWTs still refresh after backfill, existing logout remains invalid and independent sessions remain independent. A cycle test proves atomic failure with no partial family schema or token loss. Migration upgrade/downgrade/upgrade smoke is also executed.

Use a reviewed backup and a controlled cutover: **stop old application writers before migration and deploy the new code together**. Old instances neither insert required family IDs nor enforce family revocation; mixed-version rolling operation is unsupported. No live migration or deployment is performed here. Downgrade preserves token rows/revoked flags but discards family metadata and the replay guarantee; rollback/cutover needs operator review. The retained AWS migration workflow is portfolio code, not proof that an old/new service cutover is safe for this schema change.

## Proxy trust and unavailable infrastructure

Application proxy code is unchanged: the ASGI client must be the physical peer, Uvicorn must retain `--no-proxy-headers`, and trusted CIDRs must be explicitly configured. XFF is accepted only from a trusted direct peer; valid chains are walked right-to-left through configured trusted hops. IPv4/IPv6, duplicate/malformed/empty/oversized chains, untrusted private peers and spoofed prefixes are covered by existing locally executed regression tests. Invalid chains conservatively use the peer bucket. Private networks are not implicitly trusted. `Forwarded` and `X-Real-IP` do not override this decision.

The historical CloudFront -> ALB -> FastAPI design assumes maintained proxy CIDRs, CloudFront appending the observed viewer, ALB append mode without client ports, preserved socket peers, and origin/network restrictions preventing bypass. The repository does not establish the current truth of those assumptions. AWS origin restrictions, forwarding attributes, security groups, WAF, TLS, IAM, database/storage controls, maintained address ranges and actual task startup arguments are **blocked/unverified** with the closed account. No AWS authentication or API call was attempted. Local tests do not validate a live AWS deployment. See the repository's [proxy contract](23-proxy-auth-container-hardening.md).

A future VPS reverse proxy must overwrite/remove untrusted client forwarding input or append a verified socket peer, use explicit trusted CIDRs and keep the application's physical-peer contract. Merely trusting a private range or the first/last XFF element is insufficient. No VPS implementation, provider selection or cloud provisioning is part of this branch.

## Deployment safety and documentation

The AWS account is closed. Billing details/account identifiers are deliberately excluded. Historical CloudFront/ALB/ECS/RDS/Secrets Manager/CloudWatch diagrams and technical explanations remain as portfolio/design evidence. README, AWS-TECHNOLOGIES, deployment/security overview and AWS runbook now explicitly separate that design from currently unavailable operations. No public endpoint or resource is claimed live or verified.

The AWS workflow now has **only workflow_dispatch**, still requires `AWS_DEPLOY_ENABLED == true`, keeps the production environment, concurrency policy and all deployment configuration/security checks. CI completion or an ordinary merge cannot activate this branch's deploy workflow. YAML structural comparison verified the deployment steps are unchanged; static tests enforce manual-only activation and the retained gates. No GitHub production secret, variable or environment protection was read/modified or claimed verified. Normal CI tests, image builds, Trivy/security scans and publication behavior remain unchanged.

Actual GitHub required reviewers, OIDC permissions, secrets, resource health and cost controls must be revalidated after separate authorization before any future deployment. The branch does not enable an AWS workflow or dispatch it. Future hosting is a separate strict-budget decision. Containers, PostgreSQL/pgvector, Redis, credentials and explicit reverse-proxy trust remain portable application boundaries. The current production config still requires S3 storage; a non-AWS storage choice or compatible durable backend needs explicit future evaluation. No insecure ephemeral-storage production default is introduced.

The README now describes authenticated document Q&A (`POST /api/document-qa`, existing aliases and chat document mode) plus the frontend's owned-document picker. It distinguishes citation reference validation from semantic verification (`grounded=false`), retrieved sources from used citations, and the uncalibrated server score floor (0.05) from a validated quality threshold. OCR remains unimplemented. Evaluation fixtures/contract tests do not establish live-model quality. Case Workflow V2 capabilities remain documented unchanged. Local Docker Compose Quick Start was compared byte-for-byte at the section level and is unchanged.

## Validation evidence

All tests use synthetic settings and locally created disposable PostgreSQL 16/pgvector and Redis 7 services. No mock is presented as real-service/AWS evidence.

- RED: after correcting an invalid synthetic email fixture, the new pre-implementation tests reported **4 failures, 1 pass**: 201/409 registration distinction, successor usable after replay, successor usable after consumed-parent logout, and automatic AWS trigger. The first invalid-fixture attempt also failed but is not defect evidence.
- First focused GREEN: 19 passed, 1 skipped (Redis not configured for that early run). Real-service targeted execution then passed 17, skipped 0.
- First full backend: **629 passed, 0 failed/skipped**, 267 SQLAlchemy deprecation warnings, 58.08 seconds.
- Final full backend after strengthening wrong-hash, login rollback and equal-hashing-path tests: **632 passed, 0 failed/skipped**, 267 warnings, 68.70 seconds.
- Ruff **0.16.10**: check PASS; format check PASS, **110 files** formatted. No rules/configuration or dependencies were changed.
- Frontend lint, TypeScript checks and production build: PASS.
- Authentication + investigation browser suites: **60 passed, 0 failed/skipped** across Chromium, Firefox and WebKit. These use explicit API mocks and test presentation/session handling, not live AWS or real refresh races.
- YAML syntax/structure verification: PASS; manual trigger, explicit enablement and production environment confirmed; deployment step definitions and normal CI are unchanged. A full GitHub-hosted run/actionlint is not claimed from this static verification.
- Focused real-service/proxy rerun: **40 passed, 0 failed/skipped**, 10.80 seconds (`test_auth_security_v2_postgres.py`, `test_account_login_throttle.py`, `test_proxy_auth_hardening.py`): 8 PostgreSQL scenarios, 4 account-quota tests (including real Redis concurrency/TTL) and 28 local proxy cases.
- `git diff --check`: PASS. Quick Start section preservation and unchanged normal CI/dependency/proxy/case/document implementation files were checked directly.

### Complete browser matrix

Each existing project was executed in a separate process, with the same two-worker setting used by CI. No test assertions, existing skips, trace/video settings or project configuration were weakened:

```text
npx playwright test --project=<project> --workers=2 --reporter=list --global-timeout=120000
```

| Project | Passed | Failed test assertions | Skipped | Process result |
| --- | ---: | ---: | ---: | --- |
| Chromium | 47 | 0 | 1 | exit 0 |
| Firefox | 47 | 0 | 1 | exit 0 |
| WebKit | 47 | 0 | 1 | exit 0 |
| Android/mobile | 12 | 0 | 36 | exit 0 |
| iPhone | 12 | 0 | 36 | exit 1: two non-test suite/teardown timeout errors |
| Tablet | 12 | 0 | 36 | exit 1: two non-test suite/teardown timeout errors |

Totals: **177 passed, 0 failed test assertions, 111 expected skips, 4 non-test runner errors**. All scheduled test records completed; the iPhone/tablet processes timed out after their test records finished. The overall matrix command returned failure and is **not a fully green release gate**. This resembles the previously recorded Windows WebKit shutdown symptom, but this cycle does not establish its root cause or prove an environment-only explanation. No repeated retry is presented as erasing those failures. The separate 60-test desktop auth/investigation run completed successfully.

Skipped cases target desktop investigation/auth interfaces on mobile, or the existing mobile-only navigation case on desktop. The two new registration tests explicitly target the desktop session panel; no existing skip was changed. Full browser-runner completion on a clean supported runner remains a release blocker, alongside infrastructure validation.

Actual commands (project virtual-environment Python; disposable integration URLs supplied through process environment):

```text
cd backend
python -m ruff --version
python -m ruff check .
python -m ruff format --check .
python -m pytest -q --tb=short
cd ../frontend
npm run lint
npm run typecheck
npm run build
PLAYWRIGHT_WEB_SERVER_COMMAND="npm run start -- -p 3101" npx playwright test tests/e2e/auth tests/e2e/investigations --project=chromium --project=firefox --project=webkit --reporter=list --global-timeout=180000
```

## Review boundaries and remaining work

The separate critical review covers alternate auth routes, direct/indirect enumeration, keyed quota privacy, expiry/no-success-reset, family lock order, persisted hash checks before revocation, independent sessions, strict replay races, registration uniqueness races, audit rollback, migration atomicity, deployment gates and documentation overstatement. It uses the ECC security-review checklist. The pass verified persisted-hash checks before any family revocation, database lock ordering, independent-session behavior, commit-time audit rollback, no token-bearing quota/audit data, and manual deployment gating. It also caught an accidental local text-encoding change while updating a Unicode test: the original Unicode test content was restored and only the required 201-to-202 assertion remains changed. A direct diff confirmed that no Unicode boundary test, password algorithm or assertion was weakened. This is a separate pass by the implementing agent, not an external independent human audit or a hosted Codex Security scan.

Known remaining risks: indirect registration/login enumeration without email verification; temporary targeted quota denial; fixed-window bursts; access JWT validity after refresh-family revocation; strict multi-tab reauthentication; shared database privileged-tampering/retention controls; migration cutover coordination; unavailable live infrastructure/security/cost checks; current production storage constraints; and no live-provider semantic-Q&A quality validation. Full production readiness is not claimed.

## Files changed

The final Git diff is authoritative. Changes are limited to auth/family persistence and validation, account quota, its tests, generic registration UI, deployment activation guard and directly relevant documentation. Existing password tests are updated only for the intentional registration acknowledgement contract; Unicode boundaries and existing authentication/security assertions are retained. No case workflow, financial computation, document retrieval/answer implementation, proxy parser, dependency or normal CI gate is changed.

Exact files in this cycle:

- `.env.example`
- `.github/workflows/deploy-aws.yml`
- `AWS-TECHNOLOGIES.md`
- `README.md`
- `backend/alembic/versions/20261031_0007_refresh_token_families.py`
- `backend/app/api/routes/auth.py`
- `backend/app/core/config.py`
- `backend/app/core/login_throttle.py`
- `backend/app/core/security.py`
- `backend/app/models/__init__.py`
- `backend/app/models/user.py`
- `backend/app/schemas/auth.py`
- `backend/tests/test_account_login_throttle.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_auth_security_v2.py`
- `backend/tests/test_auth_security_v2_postgres.py`
- `backend/tests/test_deployment_policy.py`
- `backend/tests/test_login_hardening.py`
- `backend/tests/test_password_contract_consistency.py`
- `docs/07-security-layer.md`
- `docs/09-deployment.md`
- `docs/15-aws-cicd.md`
- `docs/30-security-hardening-v2.md`
- `frontend/src/components/auth/auth-panel.tsx`
- `frontend/src/lib/api.ts`
- `frontend/tests/e2e/auth/registration-privacy.spec.ts`
