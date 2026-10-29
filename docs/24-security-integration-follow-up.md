# Security hardening: integration follow-up

Date: 2026-10-29. Application code under test: `eb791402d377ed2313b4b425b6d8e956e3db4bee`.
Scope: browser timeout investigation, existing-volume compatibility and documented AWS
proxy assumptions. No functional application changes, dependency changes or migrations.

## Repository state

At the start, the clean local checkout was on `master`; work switched to
`security/proxy-auth-hardening` before making this documentation change. After
`git fetch origin master`, both remote branches pointed to `eb79140`. Thus the
original hardening was already present on remote master. This follow-up does not
claim a later documentation PR introduces those original security changes, and
does not rewrite master history. This session did not push master or request a deployment.

## Browser timeout investigation

The prior complete command timed out after four minutes with 111 passed, 39 skipped
and 30 tablet cases unstarted. The tablet profile passed in isolation. There was
insufficient diagnostic output to identify the historical blocked process or
attribute the timeout conclusively to the app, browser, video process or Windows.

Repeated the complete six-project matrix without changing the application or test
assertions, retaining the same 240-second global timeout:

```powershell
# From frontend, using the existing production build.
$env:PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'
$env:DEBUG='pw:browser'
$env:PLAYWRIGHT_JSON_OUTPUT_FILE='D:/projects/FinSight-AI/backend/coverage/proxy-auth-validation/browser-recheck.json'
npx playwright test --reporter=list,json --trace=retain-on-failure --global-timeout=240000
```

**PASS: exit 0, 123 passed, 57 existing viewport skips, zero unexpected/flaky
results and no runner errors; 156.013 seconds.** All six projects ran to completion:
Chromium, Firefox, WebKit, mobile Chrome, iPhone and tablet. `pw:browser` logs record
browser and FFmpeg process identifiers and successful process exits. The last
tablet browser closes with exit code 0; the runner completes normally. No blocked
worker was reproduced in this run. Trace recording does not remove existing video
or screenshot behavior and no tests were disabled to obtain the result.

A second complete run restores original trace/video defaults, removes DEBUG and
keeps the same timeout:

```powershell
Remove-Item Env:DEBUG -ErrorAction SilentlyContinue
$env:PLAYWRIGHT_JSON_OUTPUT_FILE='D:/projects/FinSight-AI/backend/coverage/proxy-auth-validation/browser-original-settings.json'
npx playwright test --reporter=list,json --global-timeout=240000
```

**PASS: exit 0, 123 passed, 57 existing viewport skips, zero unexpected/flaky
results, zero runner errors; 153.762 seconds.** This is a second successful single
complete matrix, not an aggregate across isolated projects. The historical timeout
remains of undetermined cause; no app regression was reproduced, and no timeout,
retry, skip or production-code change was used to mask it. These results justify
closing the local complete-matrix gate while retaining the original failure history.

The JSON reports and detailed console logs are ignored local validation artifacts
under `backend/coverage/proxy-auth-validation/`. Counts here describe actual runs,
not added together to disguise an incomplete single run. Browser API fixtures
remain mocked; production AWS/network behavior is not covered by these tests.
The `next start` standalone-output warning remains a test-server maintenance issue;
the production container uses `node server.js`, as verified in the previous cycle.

## Existing storage: confirmed rollout hazard, no data modification

Inspected current Docker volume inventory and metadata; no named FinSight upload
volume (`backend_uploads`) or active FinSight container was present. The remaining
named data volumes belong to other applications or the vulnerability-scanner cache
and were not touched. Two unlabelled anonymous volumes were mounted read-only with
network disabled and all capabilities dropped. Their roots are owned by 999:1000
(0755) and 999:999 (0700), respectively. Neither is established as a FinSight upload
volume; no inference about ownership migration is based on those unidentified data.
An attempted marker inspection of the 0700 directory was denied, even to UID 0 with
capabilities dropped. No permission override or data inspection was attempted after
that denial. Existing data and permissions were not changed.

To test upgrade behavior rather than fresh-volume initialization, created an isolated
labelled fixture volume `finsight-proxy-legacy-permissions-20261029`. A first root
container initialized synthetic evidence and a root-owned 0755 upload directory.
A second container reused that same volume with `volume-nocopy`, running the actual
backend image as UID 10001 with all capabilities dropped:

- Existing synthetic 0644 evidence remained intact and readable.
- The reused root-owned 0755 upload root was not writable by UID 10001.
- A root-owned 0700 user subdirectory was inaccessible to UID 10001.
- Therefore changing only the upload root is not sufficient when old descendants
  have restrictive ownership. No application fallback to root was introduced.

Commands used `docker run --rm --network none --read-only --cap-drop ALL
--security-opt no-new-privileges:true` and explicit named-volume mounts; only the
initializer ran as root, and only against the newly created synthetic fixture.
The assertions used `os.getuid()`, `os.access()` and exact synthetic file contents.
The fixture was removed after checking its task-specific ownership label.

This confirms a deployment compatibility hazard, not successful migration of a real
existing FinSight upload volume. Operator rollout steps remain:

1. Identify the actual upload mount in the target environment; record root and
   descendant ownership/modes, including staging and per-user paths. Do not alter
   unrelated database, Redis, scanner or other applications' volumes.
2. Quiesce upload writers and create a verified, restorable backup/snapshot.
3. Review and explicitly approve a narrowly scoped ownership migration to UID/GID
   10001 for the intended upload data. Avoid following symlinks or traversing other
   mounts. Preserve existing restrictive permissions and verify file contents.
4. Recreate the application as non-root and verify health/readiness, new authenticated
   upload, existing evidence accessibility and cross-user denial before cutover.

No production/bind-mount/named-upload permission migration was authorized or executed.
Real existing-upload compatibility remains a release gate until those steps are
completed in the target environment. S3 IAM/storage verification is separate.

## AWS proxy verification: deferred by the user

Read `docs/15-aws-cicd.md`, `.github/workflows/deploy-aws.yml`,
`backend/Dockerfile`, `.env.example` and the parser contract in document 23.
The deployment workflow inspects TLS/WAF/RDS/S3 posture, but does not verify ALB
XFF processing mode, client-port inclusion, trusted CIDRs, physical ECS peer identity
or application task command overrides. No repository infrastructure definition
establishes those live values. TLS/WAF checks alone do not prove the IP trust boundary.

`aws sts get-caller-identity` found no default credentials. The configured
`finsight-ai` profile returned an expired SSO session. The user explicitly requested
deferring this part; no login, infrastructure enumeration or AWS changes followed.

Automatic approval review separately rejected reading production GitHub variable
values because deployment configuration could be sensitive. Only variable names
were inspected using the permitted safer alternative. No values are included here.

The following remain unverified: ALB append mode and disabled client ports;
actual ALB/CloudFront trusted ranges; direct-origin and security-group restrictions;
the physical peer seen by FastAPI; task command retention of `--no-proxy-headers`;
and safe proxy overwriting of X-Forwarded-Proto. No production safety claim is made.

## Authentication residual risk and validation boundaries

Login throttling remains per IP, not global per account. This is explicit: an
attacker cannot exhaust an account-wide quota to lock out a victim from other IPs.
Distributed credential attacks remain a residual risk requiring a separately reviewed
account/risk/challenge policy. Registration enumeration remains unchanged.

The previous checkpoint's 423 backend passes and 89.04% coverage are historical
evidence, not a newly executed backend run in this documentation-only follow-up.
No unrelated functional changes or case-workflow work were started.

## GitHub CI and remaining release gates

The existing push-triggered [CI run for eb79140](https://github.com/remo-dif/FinSight-AI/actions/runs/40928489479)
has successful backend, frontend, security and docker-images jobs. Frontend production
build and browser E2E steps succeeded on Ubuntu 24.04. Backend PostgreSQL/Redis tests
and migration smoke succeeded, as did both image builds/scans. The dependency-review
step was skipped by its existing pull-request-only condition in that push run.
Its existing master-only image publication steps also ran; this session did not
trigger that master push or request publication/deployment.

The follow-up PR changes only these validation documents and must obtain its own
checks. A green workflow is not approval to deploy. AWS remains explicitly deferred,
real legacy upload permission migration remains unvalidated, and account-wide login
throttling remains deliberately absent. Do not mark production readiness or begin
the case-workflow integrity cycle on the basis of this local checkpoint alone.
