# Proxy, authentication and container hardening

Date: 2026-10-29. Baseline: `83127be250477f122e650eea173edf05b874ee3f`.
Branch: `security/proxy-auth-hardening`, created from freshly fetched `origin/master`
after checking a clean working tree. No push, deployment, migration or dependency change.

## Verified findings

| Finding | Classification and evidence | Resolution |
| --- | --- | --- |
| Selecting the leftmost XFF address after trusting only the direct peer | Confirmed parser defect; bypass depends on the proxy chain and header handling. `backend/app/core/rate_limit.py` | Validate the entire bounded chain; walk right to left through explicitly trusted hops. |
| Uvicorn can rewrite the ASGI client before application trust checks | Configuration-dependent risk; `backend/Dockerfile`, `backend/app/main.py` | Disable Uvicorn proxy-header processing in the image command; narrowly restore the scheme from a trusted peer. External task-command overrides require verification. |
| Missing/inactive users skip bcrypt | Confirmed execution-path discrepancy; `backend/app/api/routes/auth.py`, `backend/app/core/security.py` | Perform exactly one verification using a valid dummy bcrypt hash for these paths, retaining generic HTTP 401 and issuing no tokens. |
| Only a general IP quota protects login | Defense in depth; `backend/app/core/rate_limit.py`, `backend/app/core/config.py` | Additional bounded login IP quota in both limiter implementations. |
| Existing-email registration returns HTTP 409 | Existing enumeration/API tradeoff, deliberately unchanged; `backend/tests/test_login_hardening.py` | Documented separately; changing onboarding requires an API/UX decision. |
| Application images execute as root | Defense in depth, not evidence of a standalone remote exploit; both Dockerfiles | Dedicated UID/GID 10001, restricted writable directories, Compose capability drop and no-new-privileges. |
| Redis outage fallback, refresh rotation, authorization, exposed database ports | Previously fixed protections retained | Existing tests plus the complete service-backed suite pass. |

## Proxy trust contract and unresolved deployment assumptions

`TRUSTED_PROXY_CIDRS` contains explicit proxy address ranges, not an automatic trust of
private networks. The physical socket peer must be preserved. An untrusted peer cannot
select its identity through XFF. For a trusted peer, accept exactly one XFF header,
at most 4096 characters and 32 valid IPv4/IPv6 addresses. Reject empty entries,
malformed addresses, zone identifiers and port-bearing addresses. Invalid, duplicate,
oversized or all-trusted chains fall back to the canonical physical peer. Missing
peer information remains `unknown`. Ignore `Forwarded` and `X-Real-IP`.

For a valid chain, skip trusted addresses from right to left and stop at the first
untrusted address. Attacker-controlled prefixes before that boundary cannot change
the result. A malformed prefix can force a shared peer bucket; this conservative
fallback favors throttling over accepting an attacker-selected identity.

The repository describes CloudFront -> ALB -> ECS but does not prove live security
groups, ALB header attributes, maintained CloudFront ranges or task command overrides.
[CloudFront appends the observed viewer address](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RequestAndResponseBehaviorCustomOrigin.html).
[ALB defaults to append, but supports preserve/remove and optional client ports](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/x-forwarded-headers.html).
In that topology the application must trust the actual ALB peer ranges and verified
upstream proxy ranges to reach the viewer. Trusting only ALB stops at CloudFront's
edge address and can group many viewers into one rate-limit bucket. Do not solve
this by trusting an entire VPC or arbitrary public networks.

Before deployment, verify network ingress is restricted to intended proxies, the
origin cannot bypass intended CloudFront controls, ALB uses append with client-port
inclusion disabled, and trusted ranges are maintained. Preserve/remove modes do not
establish the assumed chain. Actual infrastructure is an unresolved release gate.

[Uvicorn has a separate proxy-header trust layer](https://uvicorn.dev/settings/).
The image uses `--no-proxy-headers` so application checks see the socket peer. Any
replacement startup command must retain this setting. The application accepts a
single exact `http`/`https` X-Forwarded-Proto value only from a trusted peer to retain
HTTPS redirects. Proxies must overwrite that field correctly. No client-IP rewriting
occurs in this scheme handling. TLS at the viewer and origin still needs independent
deployment verification; no universal bypass-elimination claim is made.

## Authentication policy and compatibility

The dummy hash is generated once per worker with the same `hash_password` function
and current bcrypt cost as real hashes. Its random source is not an account password.
Tests observe calls and responses, not wall-clock timings. Database/cache behavior
and legacy hash work factors can still differ; this is not a constant-time claim.
Response bodies, token/cookie contracts, inactive-user denial and refresh-token
rotation remain unchanged. No email/account identifier is introduced into limiter
keys or authentication errors. Redis errors log a generic warning without traceback.

`LOGIN_RATE_LIMIT_PER_MINUTE=10` (valid range 1..1000) adds a separate quota for
POST `/api/auth/login`, including successful, failed and malformed attempts. The
existing general quota also applies. HTTP 429 retains the generic body and
`Retry-After: 60`; existing Redis rate-limit response headers describe the general
quota. Redis keys contain a fixed-length SHA-256 client-IP digest, namespace and
minute window, with a 60-second TTL; IP hashing is pseudonymization, not anonymity.
Redis uses atomic INCR/EXPIRE via the existing Lua script. Memory retains its sliding
window, Redis its fixed minute window. Redis outages remain fail-closed HTTP 503.

There is no account-wide lockout: attackers cannot consume a victim's account quota
from another IP. Account-identifier throttling is deferred pending a challenge/risk
policy that avoids victim lockouts. Shared NAT clients share the quota, distributed
attacks still need perimeter controls, and bcrypt consumes CPU. The development
memory limiter retains idle dictionary entries and is not a distributed production
limiter; production continues to require Redis. No identifiers are logged here.
Registration HTTP 409 still reveals an existing address and needs a separate product
decision. Manual transaction USD defaults remain outside this security cycle.

## Container permissions and rollout

Both application images run as UID/GID 10001. Backend `/app/uploads` is owned by
that user with mode 0700; frontend `/app/.next/cache` is writable. Application source
and `server.js` remain root-owned and non-writable by the runtime user. Existing
removal of backend pip and frontend npm/corepack/yarn is retained. Compose drops all capabilities and
sets no-new-privileges for both applications. Ports and public API schemas are unchanged.

Fresh anonymous upload storage was tested. Existing root-owned named volumes or
host bind mounts may prevent startup/uploads with the new UID. Before rollout,
inspect ownership, back up data and explicitly migrate only the intended upload
directory permissions. No existing volumes were modified, deleted or recursively
chowned by this work. Existing-volume permission migration is a release blocker
until reviewed by the operator. Production S3/IAM permissions were not exercised.

## RED/GREEN checkpoints

| Stage | RED evidence | Fix checkpoint / GREEN |
| --- | --- | --- |
| Proxy | `8cda5bd`: 16 failed, 8 passed | `c1ada1c`: 29 passed, 1 optional Redis test skipped in the initial focused run |
| Authentication | `21f334a`: 7 failed, 2 passed | `38cd911`: 54 passed, 1 optional Redis test skipped in the initial focused run |
| Containers | `91fc7fe`: 5 failed | `2e7ba6f`: 19 guard tests passed; real non-root startup and upload verified |

Additional duplicate/malformed scheme and actual Redis login-expiry coverage was
added before the final full run. Final test/style/documentation changes form the
following validation checkpoint in Git history.

## Commands and results executed in this cycle

Run from repository root unless noted; Windows Python is `.venv/Scripts/python.exe`.
Synthetic credentials were used only for isolated local services, never live providers.

- Focused RED: from `backend`, `../.venv/Scripts/python.exe -m pytest tests/test_proxy_auth_hardening.py -q -p no:cacheprovider --tb=line`; corresponding authentication and container test files were run before their fixes. Results are recorded above.
- Full backend: from `backend`, with `TEST_DATABASE_URL`, `DATABASE_URL` and `TEST_REDIS_URL` pointing to isolated PostgreSQL/Redis containers, `../.venv/Scripts/python.exe -m coverage run --source=app,evaluation -m pytest -q -p no:cacheprovider --tb=short`, then `../.venv/Scripts/python.exe -m coverage report --precision=2 --fail-under=80`.
- Lint: `.venv/Scripts/python.exe -m ruff check backend`; format check for all eight changed Python files. Both pass.
- `git diff --check` and `docker compose config --quiet` pass (synthetic required environment values; no Compose deployment).
- `docker build -t finsight-ai-backend:proxy-auth-hardening backend` and `docker build -t finsight-ai-frontend:proxy-auth-hardening frontend` pass, including frontend production build/type/lint checks.
- Runtime `docker run --rm --cap-drop ALL --security-opt no-new-privileges:true ...` checks verify UID 10001, intended writable directories, non-writable source and absent backend pip. Four isolated containers verify backend health/readiness 200, frontend 200/CSP, HTTPS redirect preservation, and login statuses 401/401/401/429 while spoofed XFF prefixes change. Registration/login plus authenticated explicit-EUR CSV upload return 201/200/200, with one imported transaction. Upload directory ownership is 10001:10001, mode 700.
- Both images scanned with `aquasec/trivy:0.70.0 image --db-repository ghcr.io/aquasecurity/trivy-db:2 --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format json`: exit 0, zero fixable HIGH/CRITICAL vulnerabilities. This is not a claim of zero vulnerabilities at every severity. The scanner warns that Alpine 3.24 is absent from its EOL list; lifecycle assessment remains limited by scanner metadata.

Final backend: **423 passed, zero skipped, 27 existing SQLAlchemy deprecation
warnings; coverage 89.04%** (2793 statements, 306 missed). Rate-limit coverage is
96.12%; authentication routes 96.97%. Browser tests
use existing API fixtures, not the deployed AWS topology; real container HTTP smoke
and real PostgreSQL/Redis tests provide separate integration evidence. No live LLM,
production infrastructure, S3, managed Redis topology or GitHub CI run is claimed.

Browser commands were run from `frontend` with
`PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'`:

- `npx playwright test --reporter=list --global-timeout=240000`: **exit 1**,
  111 passed, 39 skipped, 30 did not run; suite/teardown timeout after four minutes.
  There were no reported test assertion failures, but this is not a passing full run.
- `npx playwright test --project=tablet --reporter=list --global-timeout=120000`:
  **exit 0**, 12 passed, 18 skipped in 21.8 seconds. These complete the missing
  profile's assertions, not the original run's successful teardown.

Across these runs 123 assertions passed and 57 viewport-specific cases were skipped
by existing tests. The complete matrix must finish successfully before treating the
browser release gate as validated. The runner also warns about `next start` with
standalone output; the actual frontend container uses `node server.js` and its HTTP
startup smoke passed. No unrelated browser infrastructure change was made here.

## Changed files

- `.env.example`: explicit proxy contract and login quota configuration.
- `backend/app/core/rate_limit.py`: bounded proxy parsing, trusted scheme helper and login IP quota.
- `backend/app/core/config.py`: validated login quota setting.
- `backend/app/core/security.py`, `backend/app/api/routes/auth.py`: dummy bcrypt path.
- `backend/app/main.py`: scheme handling and limiter configuration.
- `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`: non-root execution and permissions.
- `backend/tests/test_proxy_auth_hardening.py`, `backend/tests/test_login_hardening.py`, `backend/tests/test_container_hardening.py`: regression coverage.
- `docs/23-proxy-auth-container-hardening.md`: evidence, policy, rollout constraints and validation.

Release remains blocked on actual AWS proxy/ingress verification, existing-volume
permissions, a clean complete browser run and production service configuration validation. Local PostgreSQL/Redis,
production image builds and browser checks are scoped evidence, not production readiness.
