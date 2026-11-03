# HttpOnly refresh-cookie ordering: reproduction, protocol and validation

Date: 2026-11-03. Branch: `fix/auth-stale-refresh-race`.
Starting HEAD: `ef5f9255c8163a901d37e238dca8bae10704f270`.
No commit/push/PR/merge/deployment was authorized or performed.

## Confirmed finding and RED

The finding is confirmed, not just inferred. On the original backend, Chromium and real PostgreSQL authentication restored **account A after login B**, both in one tab and in two tabs sharing a cookie jar. The first RED invocation produced **2 failures, 4 deselected**. No mocked authentication JSON or synthetic Set-Cookie was used in those critical tests.

The fixture runs the real FastAPI application on a loopback HTTP listener with a fresh PostgreSQL schema. Its outer test-only ASGI transport buffers complete backend responses after authentication/rotation commits and before headers reach the browser. It exposes a barrier so login B completes before releasing A's real response headers. This is equivalent to delaying an already-produced response in transport: checking a database counter at response-generation time cannot retract these headers. The test avoids route.fetch, which could update a Playwright cookie jar before the intended release.

The old fixed-name `finsight_refresh_token` and `finsight_access_token` cookies were overwritten by late refresh A. Rejecting A's JSON in Zustand did not prevent browser Set-Cookie processing. Reload exchanged A's successor cookie for A's access JWT and `/auth/me` identified A.

## Selected protocol and invariants

1. Each successful login creates an independent existing RefreshTokenFamily (UUID F). Login sets HttpOnly `finsight_session=F.hex` and family-specific `finsight_refresh_F` / `finsight_access_F` cookies. Refresh paths remain `/api/auth`; access/selector paths remain `/`. Secure remains enabled in production, SameSite remains Lax, and no Domain attribute is added.
2. **Only login writes the selector. Refresh and logout never write or delete it.** A response issued for F can only write/delete cookies whose names include F. Therefore an arbitrarily delayed refresh/logout A cannot replace or erase B's selected credentials, even if already produced before B's login.
3. Cookie authentication accepts only the canonical selected family and its named refresh cookie, verifies the JWT/hash and existing database family association, and never falls back to another family's cookie or the legacy fixed names.
4. Refresh still consumes the presented token once, rotates its JTI/secret, hashes persisted token material, locks the family, and revokes the family on replay. No replay grace is introduced.
5. New access JWTs carry signed `sid=family UUID`. Both synchronous and asynchronous authorization check that family exists, belongs to the subject and is not revoked. Thus a late A access cookie cannot resurrect access after A logout/replay. New bound JWTs are revoked immediately with their family; pre-cutover JWTs without sid retain their prior expiry behavior.
6. The Next.js server reads only the access cookie selected by the marker. It never trusts the most recently arriving access cookie or any legacy fixed name.
7. When a tab has an access token, browser refresh sends it as a signed identity hint. For this hint only, expiry is ignored; signature/type/family must still match the cookie selection. The actual refresh credential and database checks remain mandatory. Protected browser requests with a mismatched selector/sid fail. A stale A tab therefore cannot refresh into B and replay an A action as B. Anonymous bootstrap can restore the currently selected B.
8. Cookie-mode login (`X-FinSight-Cookie-Session: true`) and refresh with no explicit JSON token return `refresh_token: ""`; the browser UI never receives the refresh secret in JSON. Explicit JSON-token clients retain their existing token exchange contract. The new header is a response-mode preference, not authorization, and is allowed by the existing explicit-origin CORS middleware.
9. The existing frontend generation guard is retained. Failed/uncertain logout still does not clear local state or claim confirmed server revocation; only the existing HTTP 204 path does so.

The selector is not a bearer credential: selecting a family without its valid refresh/access proof cannot authorize it. No migration or new application dependency is required.

## Alternatives considered

- JavaScript epochs alone: reject stale bodies but cannot stop Set-Cookie; reproduced inadequate.
- A server generation check alone: cannot stop headers generated before B from arriving afterward.
- AbortController, fetch serialization or Web Locks alone: do not prove that an already-sent response cannot modify cookies, and do not cover every tab/client.
- Stable refresh secrets / disabled rotation / replay grace: would weaken existing replay protection; rejected.
- Fixed access cookies plus an isolated refresh cookie: still allow stale server-rendered access after logout; rejected.
- Dynamic cookies without a selected family: ambiguous which account to restore; rejected. There is deliberately no fallback to an older cookie if the selected family is invalid.
- Clearing the fixed selector on logout: a delayed A logout could clear B's newer selection; rejected. Keeping a revoked selector is safe because both refresh and bound-access authorization fail closed.

## Compatibility, cutover and limits

- Existing fixed-name browser cookie sessions must sign in again. Do not run mixed old/new backend protocols while asserting the new guarantee. Coordinate frontend/backend cutover; legacy cookies are expired at login. No production action was taken.
- The selection cookie expires after configured refresh_token_days from login, and refresh cannot safely extend that fixed selector using an out-of-order response. This is an explicit absolute selection lifetime, even though rotated credentials retain their configured lifetime. Reauthentication is required when it expires.
- Older family cookie slots can remain until their ordinary expiry, including slots recreated by a delayed response. They are never fallback credentials. Many logins can consume browser cookie capacity and cause fail-closed reauthentication; automatic cookie-jar garbage collection is deferred.
- Same-session concurrent refreshes in two tabs still trigger strict replay revocation and may require login. The real browser regression tests preserve this fail-closed behavior; comprehensive cross-tab availability coordination is not implemented.
- Simultaneous login requests select the last completed login response. This work prevents refresh/logout responses from selecting an account, not a total ordering of competing login intentions.
- Authorization adds one family lookup for new bound access JWTs. Load/performance validation remains a release follow-up.
- Existing family locks, audit persistence, hashing, user isolation and authentication business rules are otherwise retained. Generic registration remains HTTP 202.
- Deployment topology, production HTTPS, cookie domains and supported real Safari environments still need release validation. Loopback tests are not production certification.

## Files and rationale

- backend/app/api/routes/auth.py: selected-family cookie protocol, browser response mode and stale-tab binding check.
- backend/app/core/security.py: signed sid issuance and family-bound sync/async authorization.
- backend/app/main.py: permit the explicit cookie-mode header within existing CORS origins.
- frontend/src/lib/api.ts: cookie-mode auth requests and current-access family hint.
- frontend/src/lib/server-data.ts: selected-family SSR access-cookie lookup.
- backend/tests/test_auth_cookie_ordering_browser.py: real HTTP/barrier fixture and browser test runner; seven scenarios.
- frontend/tests/integration/auth-cookie-ordering.mjs: actual browser cookie jar and real login/refresh/logout/me flows, plus cross-site cookie probes.
- backend/tests/test_auth_cookie_protocol.py: flags, login-only selection, expired identity hints, mismatch rejection, JSON-token compatibility and async revocation.
- backend/tests/test_auth.py: assert the new exact family-specific cookie identities, preserving security assertions.
- frontend/tests/e2e/api-failures/errors.spec.ts and auth/session.spec.ts: use the new cookie identities in existing fixtures.
- .github/workflows/ci.yml: install existing frontend dependencies and Chromium in the backend job; COOKIE_BROWSER_REQUIRED=1 makes missing browser tooling fail instead of silently skipping critical integration.
- README.md and docs/07-security-layer.md: current authentication contract and cutover implications.

## Executed validation

Backend commands ran from backend/ against temporary PostgreSQL 16/pgvector and Redis 7 containers, with synthetic keys and isolated schemas. TEST_DATABASE_URL and TEST_REDIS_URL pointed only to these loopback services. No AWS, external model provider or production database was used.

- RED: `python -B -m pytest -q tests/test_auth_cookie_ordering_browser.py -k 'switch or cross-tab' -p no:cacheprovider --tb=short`: **2 failed, 4 deselected**, both restored A.
- Initial GREEN cookie integration: **6 passed**; extended run including late logout plus auth regression subset: **42 passed**.
- `python -B -m ruff check .`: PASS.
- `python -B -m ruff format --check .`: PASS, 112 files.
- `python -B -m pytest -q -p no:cacheprovider --tb=short`, with COOKIE_BROWSER_REQUIRED=1 and real PostgreSQL/Redis: **649 passed, 0 failed, 0 skipped**, 106.29 seconds. Two Uvicorn/websockets deprecation warnings. This included Chromium cookie integration and async database revocation.
- Expanded final cookie probes: `python -B -m pytest -q tests/test_auth_cookie_ordering_browser.py -p no:cacheprovider --tb=short`: **7 passed, 0 skipped** on Chromium (46.36s); with `COOKIE_TEST_BROWSER=firefox`, **7 passed, 0 skipped** (23.44s). These final invocations include cross-site POST suppression and cookie flags, in addition to account ordering.
- Native Windows WebKit: **6 failed, 1 passed** in the initial real-cookie run, plus a follow-up single-scenario failure confirming actual cross-site cookie transmission. Every evaluated ordering result was B (or anonymous after revocation), but SameSite assertions failed: its cookie API reported None despite server Lax, and a follow-up cross-site POST probe actually sent cookies. Do not report this browser's cookie-policy validation as PASS. Upstream also marks native Windows WebKit SameSite tests as expected failures: https://github.com/microsoft/playwright/blob/main/tests/library/browsercontext-cookies.spec.ts#L131 . No application cookie flag was weakened and no test was skipped to conceal this. Repeat on supported Linux/macOS WebKit or real Safari before a cross-browser security release claim.
- Coverage command with --cov=app --cov-report=term could not run: pytest-cov is unavailable. No coverage percentage is claimed and no dependency was added solely for it.

Frontend commands ran from frontend/:

- `npm.cmd run lint`: PASS.
- `npm.cmd run typecheck`: PASS.
- `npm.cmd run build`: PASS.
- `$env:PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'` followed by `npx.cmd playwright test --project=chromium --workers=2 --reporter=list --global-timeout=180000`: **91 passed, 1 existing skip, 0 failed**.
- `npx.cmd playwright test tests/e2e/auth --project=firefox --project=webkit --project=mobile --project=iphone --project=tablet --workers=2 --reporter=list --global-timeout=240000`: **140 passed, 30 existing skips, 0 failed**. These frontend tests mostly use synthetic API routes; they do not replace the real cookie regressions above.
- Final failed-logout fixture check: `npx.cmd playwright test tests/e2e/auth/session.spec.ts --project=chromium --grep "reload restores the server session when failed logout" --reporter=list --global-timeout=30000`: **1 passed** after adding its selector cookie.
- `git diff --check`: PASS.
- CI YAML parsed locally and mandatory browser setup verified; GitHub CI was not run or claimed green.

Intermediate issues were not hidden: three old cookie-name assertions failed and were updated to exact family-specific identities; the async PostgreSQL probe initially used the unsupported Windows Proactor loop and was corrected to a test-local SelectorEventLoop; a cross-site probe initially exhausted the fixture's default rate budget, so only the test fixture budget was increased to include its extra control requests. Production limits are unchanged.

The real-cookie harness serves a minimal bootstrap document using actual backend refresh/me endpoints; it is not a full deployed Next.js/HTTPS test. Next.js SSR selection is covered separately by source inspection and frontend regressions. Native Windows WebKit validation and full production integration remain open. No production readiness is claimed.
