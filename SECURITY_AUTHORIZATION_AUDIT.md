# FinSight-AI Authentication & Authorization Audit

Date: 2026-10-29  
Scope: local source review and automated tests for authentication, refresh-token handling, object-level authorization, cookie/CSRF behavior, rate limiting, and frontend token handling. No public services or production data were accessed.

## 1. Executive summary

The focused review found no confirmed JWT acceptance bypass or broken object-level authorization in the reviewed API routes. Access and refresh JWTs are cryptographically and semantically separated; expiry is validated by JWT decoding; inactive users are rejected; refresh tokens are stored as SHA-256 hashes and consumed with a conditional update; and transaction, case, note, and chat-session queries are scoped to the authenticated user.

One low-severity session-cookie configuration defect was confirmed and fixed: the refresh cookie previously persisted for 30 days regardless of the configured JWT refresh lifetime (7 days by default). Cookie `Max-Age` now follows the configured refresh-token expiry, with a regression test.

One session behavior is confirmed but intentionally unchanged pending a product/security decision: logout revokes the presented refresh token and clears cookies, but already-issued access JWTs remain valid until their short expiry (30 minutes by default). Immediate access-token revocation requires server-side state or a different token/session scheme. The task explicitly requires presenting session-semantic changes before implementation, so no such change was made.

## 2. Git branch and working tree

- Default branch identified as `master` (`origin/HEAD` -> `origin/master`).
- Fetched `origin` and created `security/auth-authorization-audit` from fetched `origin/master` at `de5065aa786f948353821d515699171ce387f553`.
- The named branch did not previously exist locally or on the remote.
- No commit, push, merge, or pull request was made.
- Working tree contains only the intended source/test/report changes: [auth.py](backend/app/api/routes/auth.py), [test_auth_authorization_audit.py](backend/tests/test_auth_authorization_audit.py), and this report.

## 3. Existing security controls

- [security.py](backend/app/core/security.py:41): access and refresh tokens have distinct `type` claims and distinct configured signing secrets; JWT decoding restricts the algorithm to the configured algorithm and checks expiration.
- [security.py](backend/app/core/security.py:122): sync and async auth dependencies require `type=access`, parse UUID subjects, load the user, and reject missing or inactive users.
- [security.py](backend/app/core/security.py:73): refresh tokens have random JTIs and persist only a SHA-256 token hash plus expiry/revocation metadata.
- [auth.py](backend/app/api/routes/auth.py:132): refresh checks signature/type, JTI, subject, hash, user status, database expiry, and revocation, then uses a conditional update as compare-and-set before issuing a replacement. The existing stale-reader regression is in [test_security_hardening.py](backend/tests/test_security_hardening.py:49).
- [test_auth.py](backend/tests/test_auth.py:103): tests cover rotation, predecessor revocation, and rejection of reuse; [test_auth.py](backend/tests/test_auth.py:138) covers refresh-token logout revocation.
- [cases.py](backend/app/repositories/cases.py:17): case list, detail, and note reads join through transactions and filter by `Transaction.user_id`. Case mutation and note creation resolve the case through this same user-scoped repository first: [cases.py](backend/app/api/routes/cases.py:86), [cases.py](backend/app/api/routes/cases.py:155).
- [transactions.py](backend/app/repositories/transactions.py:67): transaction list and analytics queries are scoped by authenticated `user_id`; new transaction records derive ownership from the current user in [transactions.py](backend/app/repositories/transactions.py:57).
- [uploads.py](backend/app/api/routes/uploads.py:19): upload creation is authenticated and writes the current user's ID to the evidence row/storage namespace. No evidence download/get-by-ID API route was found in the reviewed router.
- [chat.py](backend/app/api/routes/chat.py:24): supplied chat-session IDs are looked up by both session ID and owner ID, including a post-provider-call ownership recheck.
- [auth.py](backend/app/api/routes/auth.py:37): access and refresh cookies are `HttpOnly`, `SameSite=Lax`, and use `/` and `/api/auth` paths respectively; `Secure` is enabled in production. Clear-cookie operations retain matching paths.
- [session.ts](frontend/src/store/session.ts:13): Zustand persistence explicitly serializes only the chat session ID, not the access token. The token remains in client memory and is attached as a Bearer header by [api.ts](frontend/src/lib/api.ts:156). Auth JSON responses still contain both tokens, matching the existing frontend contract.
- [rate_limit.py](backend/app/core/rate_limit.py:87): Redis-backed rate limiting uses a trusted-proxy-aware client IP and fails closed with 503 when Redis is unavailable. Production config requires Redis; the fallback memory limiter is per-process and therefore suitable only for non-production/single-process use.

## 4. Confirmed vulnerabilities and fixes

### Low — refresh cookie lifetime exceeded refresh JWT lifetime (fixed)

- Evidence: [set_refresh_cookie](backend/app/api/routes/auth.py:58) used a hard-coded 30-day cookie lifetime while [security settings](backend/app/core/config.py:35) default the refresh token itself to 7 days. The JWT and database expiry checks prevented the stale cookie from authenticating after expiry, so this was not a token-expiry bypass, but it retained an unusable credential in the browser longer than configured.
- Attack scenario / impact: a refresh cookie may remain on a shared browser after its token has expired, increasing unnecessary credential retention; it cannot be successfully refreshed once JWT/database expiry has passed.
- Fix: cookie `Max-Age` is now computed from `settings.refresh_token_days`.
- Verification: regression test [test_refresh_cookie_lifetime_matches_configured_refresh_token_lifetime](backend/tests/test_auth_authorization_audit.py:65) sets an 11-day lifetime and verifies `Max-Age=950400`, `HttpOnly`, `SameSite=Lax`, and the scoped path.

### Medium — access JWT remains valid after logout (confirmed behavior; not changed)

- Evidence: [logout](backend/app/api/routes/auth.py:188) revokes only the presented refresh-token row and clears both cookies. [get_current_user](backend/app/core/security.py:122) validates the access JWT and active user but does not consult refresh-token revocation/session state. Thus a previously issued access bearer token remains accepted until `exp` (default 30 minutes) even after logout.
- Attack scenario / impact: if an access token has been copied before logout (for example, from an active browser context), its holder can continue authenticated requests until expiry. The frontend clears its in-memory token, but this does not revoke a copied bearer token.
- Classification: confirmed session limitation, not an authentication bypass; exploitation requires prior access-token disclosure.
- Required decision before a fix: choose immediate revocation semantics. A denylist keyed by access-token JTI would require adding a JTI to access tokens, durable/shared revocation storage and an expiry cleanup policy, and a database or Redis lookup on authenticated requests. A per-user token-version/session design has similar shared-state and migration implications. Either keeps current response shapes but changes session invalidation semantics and adds operational state. No implementation was made without that decision.

## 5. Plausible risks requiring further investigation

- **Refresh-token family revocation after reuse:** consumed refresh tokens are rejected, and compare-and-set prevents a stale competing reader from winning a second rotation. Reuse does not revoke the replacement/descendant token chain; the model has `replaced_by_jti` but no family identifier. A stolen old token alone cannot be replayed successfully after rotation, but family-level revocation can improve compromise containment when token theft is suspected. Implementing it requires session semantics/storage changes (likely a family identifier/migration) and is not included.
- **Cookie-based auth CSRF edge cases:** main API routes use Bearer auth, while refresh/logout accept a refresh cookie. Cookies are `SameSite=Lax`, reducing ordinary cross-site POST exposure, and credentialed CORS is limited to configured origins. No direct CSRF bypass was reproduced. Reassess if deployment uses same-site untrusted subdomains, broad origin trust, or changes cookie policy; origin verification/CSRF tokens would be a compatibility-sensitive enhancement.
- **Token exposure during active page execution:** login/refresh return access and refresh tokens in JSON to preserve the established API contract. Frontend state does not persist either token to local storage, but the access token is JavaScript-readable in memory and can be exposed by an XSS. No XSS or token-logging path was confirmed in this scoped review.
- **Rate-limit granularity:** current limit is by client IP, not account/endpoint. Distributed production enforcement is configured, but credential-stuffing resistance can be weakened by distributed source IPs. Consider endpoint/account-aware login throttling with safe lockout behavior as a separate change.

## 6. BOLA/IDOR review results

No confirmed BOLA/IDOR was found in reviewed user-scoped endpoints. Synthetic User A/User B tests exercise case listing/detail/update, note creation/read via detail, and transaction listing. UUID replacement with another user's transaction/case ID returns 404 for object operations; list endpoints omit the other user's records. Tests also compare case status/assignee/decision, note count, and audit-log count before and after unauthorized requests.

Evidence storage is currently write-only through the API router; no user-facing evidence retrieval-by-ID route was found. The upload flow binds uploaded metadata and storage paths to the authenticated user. This audit did not test cloud bucket policy or external storage configuration.

## 7. Files modified

- [auth.py](backend/app/api/routes/auth.py:58): align refresh-cookie lifetime with configured refresh-token lifetime.
- [test_auth_authorization_audit.py](backend/tests/test_auth_authorization_audit.py): add API-level JWT rejection, token-type separation, inactive-user, cross-user case/note/transaction, database non-mutation, and cookie-contract regression tests.
- [SECURITY_AUTHORIZATION_AUDIT.md](SECURITY_AUTHORIZATION_AUDIT.md): this evidence-based audit report.

No frontend files, session schema, migration, dependency, cloud configuration, or API response contract was changed.

## 8. Regression tests and commands/results

- Focused auth/security/case tests: `22 passed, 25 warnings`.
- Full backend suite: `328 passed, 2 skipped, 27 warnings`.
- Ruff: `All checks passed!`.
- `git diff --check`: passed.
- Tests ran with the repository virtualenv, a synthetic in-memory SQLite database URL, and synthetic JWT secrets. No PostgreSQL or Redis service was used; the two skipped tests remain skipped by their existing test configuration.
- The warnings are existing SQLAlchemy `Result.tuples()` deprecation warnings in the cases repository; this audit did not refactor unrelated code.
- Frontend tests were not run because no frontend behavior/source changed.

## 9. Remaining security limitations

- Access JWTs are not revoked immediately on logout; effective revocation is bounded by access-token expiry.
- Reuse of a consumed refresh token is rejected but does not revoke its token family.
- CSRF behavior relies primarily on `SameSite=Lax` plus configured CORS for cookie-based refresh/logout flows; deployments with same-site untrusted origins warrant additional controls.
- The tests use SQLite and do not establish PostgreSQL-specific refresh races or production Redis behavior. Existing stale-reader coverage exercises compare-and-set behavior but is not a load/stress test of truly simultaneous PostgreSQL requests.
- The scoped review did not include cloud IAM/bucket policy, deployment ingress/proxy configuration, production logs, or independent penetration testing.

## 10. Three highest-priority next steps

1. Decide whether logout must immediately revoke outstanding access JWTs. If yes, select a shared revocation/session-state design, define migration and availability behavior, then add cross-worker concurrency and logout regression tests.
2. Decide whether detected refresh-token reuse should revoke the full token family, including the data model, migration, audit event, and concurrent-request behavior.
3. Validate deployed cookie/CORS/proxy and Redis rate-limit configuration, then add endpoint/account-aware login throttling and production-like PostgreSQL/Redis tests where available.

This report does not claim independent audit, penetration testing, or production readiness.
