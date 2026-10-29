# Dependency security correction and resumed validation

Date: 2026-10-29. Tested application commit: `12cfc6e`.

## Scope and checkpoints

The baseline CI run `40896715041` for `8119399` passed application tests but
failed Trivy image scans: backend 5 HIGH; frontend 12 HIGH and 3 CRITICAL.

- `5f355b3`: initial RED dependency regression tests, 8 expected failures.
- `12cfc6e`: dependency, packaging and CI corrections. Before the additional
  npm fixes, the expanded regression suite recorded 5 failures and 8 passes.
- No authentication, financial semantics, API, schema or migration changes.
  No push, image publication or deployment was performed by this task.

## Corrections

- Keep Next.js on the 15.x line: `next` and `eslint-config-next` 15.5.28.
- Override existing transitive dependencies: nanoid 3.3.18, sharp 0.35.5,
  source-map-js 1.2.2; use the shared PostCSS dependency (resolved 8.5.32).
- Refresh compatible development-tool dependencies reported by npm audit:
  baseline-browser-mapping, brace-expansion, browserslist, js-yaml and
  postcss-selector-parser. No forced major upgrades or new application libraries.
- Add Python security constraints for existing dependencies: msgpack >=1.2.3,
  urllib3 >=2.8.0, setuptools >=78.1.1. Apply them in CI and image builds.
- Raise the setuptools build requirement, upgrade build tooling, run `pip check`,
  then uninstall pip from the final backend image. This removes its vendored
  dependencies, which ordinary application constraints cannot update.
- Add CI `pip check` and `npm audit --audit-level=high`; preserve the existing
  blocking Trivy HIGH/CRITICAL policy, without ignore entries or relaxed severity.

Changed implementation files: `.github/workflows/ci.yml`, `backend/Dockerfile`,
`backend/constraints-security.txt`, `backend/pyproject.toml`,
`backend/tests/test_dependency_security.py`, `frontend/package.json`, and
`frontend/package-lock.json`.

## Commands executed after Docker recovery

Commands below used synthetic credentials and isolated temporary PostgreSQL
with pgvector and Redis services, not existing application databases.

- `docker build --pull -t finsight-ai-backend:security-fix ./backend`
- `docker build --pull -t finsight-ai-frontend:security-fix ./frontend`
- In backend, with `TEST_DATABASE_URL` and `TEST_REDIS_URL` set:
  `python -m coverage run --source=app -m pytest -q -p no:cacheprovider --tb=short`
- `python -m coverage report --precision=2 --fail-under=80`
- `python -m ruff check app tests --no-cache`; `python -m pip check`
- Repeat the backend suite in an ephemeral container derived from the built
  image, with a writable archive of the tested commit. Install pytest,
  pytest-asyncio, httpx, coverage and Ruff only in that disposable container;
  the original scanned runtime image remains unchanged and contains no pip.
- In frontend: `npm audit`, `npm run typecheck`, `npm run lint`.
- Trivy 0.70.0, matching the version in the failed CI logs, on each built image:
  `image --db-repository ghcr.io/aquasecurity/trivy-db:2 --scanners vuln
  --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format json`.
- Playwright matrix: `playwright test --reporter=list --global-timeout=240000`,
  with `PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'`.

## Results

| Check | Result |
| --- | --- |
| Backend Windows, with PostgreSQL/Redis integration tests enabled | 343 passed, 0 skipped, 27 deprecation warnings |
| Backend Linux image dependencies, same integration tests enabled | 343 passed, 0 skipped, 27 deprecation warnings |
| Backend coverage, both environments | 85.70% (2524 statements, 361 missed) |
| Ruff and pip dependency compatibility | PASS in both environments |
| Frontend image production build, TypeScript and ESLint | PASS |
| npm audit, including development dependencies | 0 vulnerabilities |
| Backend Trivy gate | PASS, 0 HIGH/CRITICAL fixable findings |
| Frontend Trivy gate | PASS, 0 HIGH/CRITICAL fixable findings |
| Playwright final matrix | PASS, exit 0: 123 passed, 57 existing skips, 2.8 minutes |
| Final backend runtime smoke | `/health` 200, `/readyz` 200, unauthenticated `/api/transactions` 401 |
| Native sharp runtime smoke | sharp 0.35.5 generated a 90-byte PNG successfully |

Local evidence is retained under the git-ignored
`backend/coverage/dependency-validation-20261029b/`, including both Trivy JSON
reports, the Linux coverage data and the source archive used in that container.

Scanned image IDs:

- Backend: `sha256:7772fc59ec7d196b73b2937a8747fe062139a2dc5fcf54b8e07b2e3e0b3a1050`
- Frontend: `sha256:5b69a418cd21273247e4dee84d19efd9d143ad75b8e607135fbb63b31bf5831d`

## Failed or incomplete attempts, not application regressions

- The cache retained from the full-disk interruption caused a Trivy bbolt panic.
  A fresh dedicated cache was used, without deleting the old volume. A subsequent
  mirror download returned unexpected EOF; the official GHCR download succeeded.
- The first Linux suite mounted the repository read-only: 339 passed, 4 failed
  because existing tests write temporary files in the source tree. The corrected
  writable disposable-copy run passed all 343 tests without changing app code.
- All cases in the Docker-hosted browser attempt emitted results, but its worker
  hung during shutdown. That run was interrupted and is not claimed as a clean
  successful run; the CI-style production-server matrix was rerun separately.
- An initial sharp probe queried an unexported `sharp/package.json` path. Using
  the public `sharp.versions.sharp` property confirmed successful image processing.
- Initial guessed HTTP paths `/healthz` and `/api/v1/transactions` returned 404;
  the routes actually defined by this application passed the checks above.

## Remaining limitations and release gates

These results do not establish production readiness. Browser API calls are
mocked by the existing suite, not a complete live browser-to-backend deployment
test. PostgreSQL migration smoke and Redis integration tests pass, but most unit
fixtures still use SQLite; do not interpret the count as comprehensive PostgreSQL
coverage of every business query. Live S3/IAM, remote embedding/LLM providers and
production deployment configuration still require validation.

Trivy counts here intentionally follow CI filters: HIGH/CRITICAL with available
fixes. They do not mean every severity or unknown vulnerability is absent.
Trivy 0.70.0 warns that Alpine 3.24 is not in its EOL list; both OS and language
vulnerability scans nevertheless ran. A future scanner upgrade should be
reviewed separately. Python dependencies and base images are not fully locked,
so future fresh builds may resolve differently. Version-floor regression tests
are safeguards, not exploit proofs or substitutes for ongoing image scans.

Manual transaction creation's existing USD default remains deferred and unchanged.
This validation does not close unrelated security or financial findings.

Final verdict: **PASS for this dependency-correction validation**, not production
readiness. The resumed checks did not modify application code. Only this report
was added after the tested application commit. The temporary API, PostgreSQL,
Redis and browser containers and the dedicated validation network were closed;
pre-existing Docker images, containers and volumes were not pruned. At the final
check C: retained approximately 28.1 GiB free, with Docker's disk image on D:.
