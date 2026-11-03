# Frontend authentication session race

Date: 2026-11-03. Branch: `fix/auth-stale-refresh-race`.
Baseline: `5e9cd2ada4cb65d268f462009fa06ee7b37e361f` (latest fetched origin/master).

## Root cause and scope

SessionBootstrap mounts and starts restoreSession without blocking login. The old performTokenRefresh unconditionally cleared or replaced the Zustand access token after an asynchronous refresh. A single global pending promise also allowed a new session to join an older session's request. No guard separated normal token rotation from an actual session transition.

Only frontend authentication state, API request coordination, focused tests and this report are changed. Existing user configuration (.gitignore and ignored .github/skills) is preserved. No backend, database, API contract, dependency, accessibility, case workflow or CI changes are included. ECC security-review and TDD guidance was used; the explicit instruction not to commit overrides skill checkpoint guidance. No commit, push, PR, merge, AWS access or deployment is authorized/performed.

## Concurrency semantics

- sessionGeneration is in-memory only, alongside the existing non-persisted access token. Persisted state still contains only chatSessionId.
- Explicit setAccessToken (login/replacement), clearSession (including null-to-null local clearing) and logout initiation increment the generation.
- Logout initiation fences older refresh results without clearing the current token. Only the existing confirmed HTTP 204 UI path clears the session; errors/timeouts keep existing uncertain-outcome handling.
- A refresh captures its generation. Failure may clear state only while that generation remains current. Successful token application is checked again atomically in the store, including after asynchronous JSON decoding.
- A stale result returns null to its original caller rather than borrowing the newer session's token.
- Normal refresh rotation preserves the generation. Outstanding requests in that same session remain valid.
- Refreshes coalesce within one generation. A new generation gets its own flight. The finally callback releases the pending slot only if it still owns that slot.
- Authenticated API calls capture generation and check it across asynchronous boundaries. An old account's failed action cannot be retried with a different account's token; a body decoded after an account switch is rejected. Within the same generation, a late 401 reuses an already-rotated token rather than initiating another rotation.
- SessionBootstrap continues to restore on mount; login is not serialized behind restoration and no bootstrap delay hides the race.

## Regression evidence

Initial RED run, against baseline production build: **12 failed, 2 passed**. Failures included both actual browser overlaps (old bootstrap 401 after new login; old bootstrap 200 overwriting the token observed on a subsequent authenticated detail request), network/503 paths, local clearing, logout fencing, different-generation flights and cross-session action replay. The two passing controls covered valid same-session rotation behavior.

The browser tests hold bootstrap at a route barrier, complete real UI login with a distinguishable token, then release bootstrap. They never wait for bootstrap completion before logging in. Store/API tests use actual production modules with controlled fetch promises, not a reimplementation of generation logic. Additional tests cover late JSON bodies. Browser assertions check both authenticated UI and Authorization on a subsequent case request.

Initial GREEN: **14 passed**. After adding late-body tests, repeated run: **160 passed, 0 failed, 0 skipped** (16 scenarios, 10 repeats, 2 workers).

## Commands actually executed

Windows' PowerShell execution policy blocked npm.ps1, so npm.cmd/npx.cmd were used without changing system policy. All commands below ran in frontend/:

- `npm.cmd run lint`: PASS.
- `npm.cmd run typecheck`: PASS.
- `npm.cmd run build`: PASS.
- PowerShell web-server setting: `$env:PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'`.
- RED: `npx.cmd playwright test tests/e2e/auth/session-concurrency.spec.ts tests/e2e/auth/stale-bootstrap.spec.ts --project=chromium --reporter=list --timeout=15000 --global-timeout=90000`: 12 failed, 2 passed.
- Repeated GREEN: `npx.cmd playwright test tests/e2e/auth/session-concurrency.spec.ts tests/e2e/auth/stale-bootstrap.spec.ts --project=chromium --repeat-each=10 --workers=2 --reporter=list --global-timeout=120000`: 160 passed.
- `npx.cmd playwright test --project=chromium --workers=2 --reporter=list --global-timeout=180000`: **91 passed, 1 existing skip, 0 failed** (full Chromium suite).
- `npx.cmd playwright test tests/e2e/auth --project=firefox --project=webkit --project=mobile --project=iphone --project=tablet --workers=2 --reporter=list --global-timeout=240000`: **140 passed, 30 existing skips, 0 failed**. The skips are ten existing tests per mobile profile; the two new browser overlaps and the already-present core logout/uncertain-outcome/restoration tests ran on the mobile profiles. No teardown errors.

These are separate invocations with overlapping tests, not a count of unique scenarios. The full non-auth suite was not rerun on every engine. Backend integration and instrumented frontend coverage: NOT RUN; no backend changes or new coverage dependencies.
- `git diff --check`: PASS.

Non-browser module tests emit Zustand's storage-unavailable warning because the Node worker has no browser localStorage; they test memory state. Browser tests separately exercise the real persisted-store environment. Next's pre-existing standalone/next-start warning is unchanged. No coverage percentage is claimed. No tests are removed, weakened or newly skipped.

## Boundaries and remaining limitations

The generation and single-flight slot belong to a single JavaScript context. Cross-tab refresh coordination is NOT implemented. Strict backend refresh replay detection and family revocation remain unchanged.

These guards protect JavaScript session state and authenticated client retries. They do not control browser application of HttpOnly Set-Cookie headers from outstanding HTTP responses. Browser overlap tests deliberately distinguish response tokens but do not claim to solve cookie-level reordering between concurrent server login/refresh responses. That needs a separate protocol/coordination review; ignoring a JSON result is not proof that the browser ignored its cookie headers.

Fencing a failed logout retains the token and permits subsequent explicit recovery, but does not guarantee serialization of every server-side operation across generation boundaries or tabs. Existing access JWT expiry, uncertain logout outcome and server family semantics remain in force.

Tests use synthetic API responses and do not establish production PostgreSQL/Redis/browser integration. No production-readiness or GitHub-CI success claim is made. Backend integration is not rerun because backend behavior is unchanged.
