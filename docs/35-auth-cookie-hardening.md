# Cookie tossing and authentication cutover

Reviewed baseline: `23933f9668434609ea74b6f7288f9ab5cbd2a1a7`. Work began on `fix/auth-stale-refresh-race` at `c2f54e5`, which already included the Ruff and Ubuntu runner fixes.

## Selector and family cookies

The original unprefixed selector could be duplicated by a sibling using a parent-domain cookie. In a real HTTPS Chromium run against 23933f9, login B followed by injection of A's selector restored A after navigation. This was account confusion through the actual browser jar and PostgreSQL-backed FastAPI authentication.

Production and staging select only `__Host-finsight_session` and the associated `__Host-finsight_access_<family>` and `__Host-finsight_refresh_<family>` cookies. These cookies are Secure, HttpOnly, host-only, SameSite=Lax and Path=/. The root path is required by the prefix and widens refresh-cookie transmission on the trusted application host. Review ingress forwarding and cookie redaction before deployment. Prefix enforcement on supported browsers prevents parent-domain injection. The application separately rejects duplicates, even duplicates with identical values. See [Set-Cookie prefix rules](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie#cookie_prefixes).

Backend refresh, logout and sync/async authorization inspect raw Cookie fields before selecting a session. The selected refresh cookie must be unique. Next.js SSR also reads the raw header and requires a unique selector and selected access slot. The selector must be a canonical 32-character lowercase UUID hex value. HTTPS modes do not consult legacy names. A production user with the old cookie names signs in again.

HTTP development keeps unprefixed cookies on loopback, with the existing narrow refresh path. Compose binds published frontend/backend ports to loopback. The frontend must opt in with `FINSIGHT_LOCAL_HTTP_COOKIES=true` on a loopback Host and outside staging/production. Compose and Playwright set this explicitly. A manually started local frontend needs the same setting. Development cookie mode is unsuitable for shared domains.

Only login sets the selector. Refresh and logout write or expire only their own family slots. An A request cannot rotate or act as B after the browser selects B. Cookie-mode responses retain the empty refresh-token field, and explicit JSON-token clients retain their credential exchange. Family rotation, replay revocation and confirmed-204 logout semantics remain covered. Competing successful logins use the last response applied by the browser. The test documents that policy, which is distinct from ordering refresh or logout.

## Bounded cleanup

On successful login the server emits at most 16 deletions for validated family slots present in that request, in addition to the existing two legacy-name expirations. A login creates a fresh UUID, so a concurrent later login's new slots could not have appeared in the earlier snapshot. The selector and new slots are excluded from cleanup. An older refresh may recreate its own expired slot, which stays unselected and expires according to the existing access or refresh lifetime. Deleting browser slots does not revoke separate server families.

Sequential switching retains two family slots plus the selector in the browser test, with a synthetic auth Cookie header under 2 KiB. This is a measured test budget rather than a browser or proxy limit. Many concurrent outstanding responses can retain more slots until expiry or subsequent login cleanup. A deployment must validate its browser and ingress cookie/header budgets. If a client hits an ingress header limit, clearing site cookies and signing in again is the recovery path. No fallback picks a retained family.

## Cutover and rollback gate

An executable comparison used the same valid signed access JWT after logout. The verifier from ef5f925 accepted it and the current verifier returned 401. Shared keys on old and new instances therefore permit a revocation bypass while old instances can still receive requests.

A coordinated drain is the smallest safe strategy for the retained ECS topology. A compatibility release could teach every reader to enforce sid before any writer issues it, but requires verified deployment sequencing. Key/version isolation can make old readers reject new JWTs, but needs separate credential distribution and still requires coordinated cookie routing.

The retained deployment workflow exits before checkout or AWS credentials. The gate is intentionally blocking until an operator can enforce and attest all of the following outside this repository:

1. Restrict deployment credentials to the reviewed workflow and protected ref. Disable old deployment definitions and any alternate deployment path capable of bringing old readers back.
2. Close authentication and protected traffic at ingress, including direct origin and internal routes. Drain requests and confirm zero reachable old backend instances or targets across every traffic path. Desired replica count alone is insufficient.
3. Bring up only family-aware backend and matching frontend revisions. Verify runtime HTTPS mode, host-only cookie attributes, legacy-cookie reauthentication, refresh/logout ordering, and a real revoked-family 401 through each ingress before reopening traffic.
4. Roll back only to a compatible family-aware build while issued keys are shared. If an older verifier is unavoidable, close traffic and drain first. Isolate it from all tokens minted by the new protocol, including with fresh signing material before reopening and forced reauthentication. Do not route new tokens to an old verifier that shares their signing key.

No infrastructure state or live operational gate was verified. Production remains blocked until external enforcement is implemented. A workflow edit on this branch cannot control old refs or deployments made elsewhere.

## Files

- `backend/app/core/session_cookies.py` centralizes raw Cookie parsing, secure naming and selector validation.
- `backend/app/api/routes/auth.py` applies names, scoped writes and bounded cleanup. `backend/app/core/security.py` uses the same selector validation in both authorization dependencies.
- `frontend/src/lib/server-data.ts` validates raw selector/access cookies before SSR.
- `docker-compose.yml` and `frontend/playwright.config.ts` configure loopback HTTP development and testing.
- `.github/workflows/deploy-aws.yml` blocks unsafe deploys.
- `backend/tests/test_auth_cookie_ordering_browser.py` and `frontend/tests/integration/auth-cookie-ordering.mjs` run actual browsers and FastAPI/PostgreSQL with held response headers.
- `backend/tests/test_auth_cookie_protocol.py` covers raw duplicate fields and the HTTPS response contract. `frontend/tests/e2e/api-failures/errors.spec.ts` covers SSR duplicate handling.

## Evidence

The browser harness uses a real HTTP(S) listener and PostgreSQL-backed authentication. It buffers actual backend headers after the application completes. The sibling case uses HTTPS and two real browser hostnames. The stale-401 case revokes A's family without deleting its cookie, captures the outgoing request carrying that refresh cookie, holds the 401, and confirms B after browser navigation. Contract assertions about empty JSON refresh tokens run separately from baseline ordering assertions.

- RED on ef5f925 using `python -B -m pytest -q tests/test_auth_cookie_ordering_browser.py -k 'switch or cross-tab' -p no:cacheprovider --tb=short`: 2 failures, A restored in both cases.
- RED on 23933f9 with `-k sibling`: 1 failure, A restored after the sibling injection. The same harness was copied to isolated baseline archives, with only its frontend script path adjusted.
- First full backend pass with isolated PostgreSQL/Redis using `python -B -m pytest -q -p no:cacheprovider --tb=short`: 653 passed. Final results are recorded below.
- The original real-cookie GREEN run passed all 11 scenarios on Chromium and Firefox. A separate stale-tab binding scenario was subsequently added to preserve coverage without contaminating the RED ordering assertions.
- Native Windows WebKit with `COOKIE_TEST_BROWSER=webkit` and `-k 'not sibling'`: 3 passed, 7 failed, 1 deselected in the 11-case snapshot. Ordering outcomes were as expected. Failures were actual cross-site cookie transmission despite SameSite=Lax. The sibling TLS case was not run on that port. Linux/macOS WebKit and Safari were not run. See [upstream Windows WebKit SameSite expectations](https://github.com/microsoft/playwright/blob/main/tests/library/browsercontext-cookies.spec.ts#L131).
- Frontend Playwright auth/API-failure suites exercise UI and SSR with synthetic API fixtures. They complement rather than replace the real backend cookie tests.
- Same-family concurrent refresh still invokes strict replay revocation, so separate tabs can need reauthentication. Full cross-tab refresh coordination remains out of scope.

Final validation:

- Full backend command above: 655 passed, zero failures or skips, with disposable PostgreSQL/pgvector and Redis, including all 12 Chromium cookie cases.
- Firefox with COOKIE_TEST_BROWSER=firefox and python -B -m pytest -q tests/test_auth_cookie_ordering_browser.py -p no:cacheprovider --tb=short: 12 passed.
- Ruff 0.17.3: python -m ruff check . and python -m ruff format --check . passed (113 Python files).
- npm run lint, npm run typecheck and npm run build passed. The first targeted frontend Playwright auth/API-failure run passed 82 tests. The final Chromium/Firefox run recorded passed in the Playwright state file and the final suite enumerated 84 cases. The final reporter counts were unavailable.
- git diff --check passed. Static YAML parsing verified the AWS gate precedes checkout and credential acquisition. Hosted CI and deployment were not run.
