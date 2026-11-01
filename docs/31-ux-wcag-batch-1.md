# UX Integrity and WCAG 2.2 AA Remediation — Batch 1

Date: 2026-11-01. Branch: `feature/ux-wcag-batch-1`.

## Baseline and scope

The existing UX branch started at `80ef865f302a499705b2f0212619bd1aa6ff20e2`, the Security Hardening V2 squash merge (PR #11, including head `c3c2eb263cece8e70ceba50bcdfa1599cb644d9b`). At implementation time master had advanced to `10f89ebda157d8251863efd49f4eb3590163f56e` (merged PR #12). The clean UX branch was fast-forwarded to that master. No unmerged minimatch branch was merged or cherry-picked. Package manifests, lockfile, backend, migrations and CI have no changes relative to that baseline.

ECC accessibility, frontend-a11y, browser-qa, security-review and TDD guidance was applied. No ECC installation or configuration changes were made. No AWS calls or production migrations were performed.

## Findings and implementation

| ID | Root cause | Remediation | Criteria |
| --- | --- | --- | --- |
| UX-01 | React retained decision/reason/note state when selected-case props changed; asynchronous callbacks depended on the current component's props; PATCH/note conflicts did not refresh detail. | Key the workflow by case identity and mutation permission. Pass immutable case ID, observed revision and payload as mutation variables. Target cache updates/refetches using those variables. Explicitly disable mutation retries and refetch the affected case on HTTP 409. | Case workflow integrity |
| A11Y-01 | Placeholder alpha reduced contrast against white. | Remove alpha from placeholder utility classes; use the existing muted text token with opacity 1. Measured RGB 71/84/102 against white: 7.6982:1 (before: 3.6210:1). | 1.4.3 |
| A11Y-02 | Decorative separator token also defined essential input boundaries. | Separate control-border token (RGB 94/111/135), 5.1225:1 against white. Invalid fields retain a danger border plus textual errors and semantic invalid state. Existing keyboard focus styling remains. | 1.4.11 |
| A11Y-03 | Fixed columns, hidden overflow, ellipsis and non-wrapping amounts/IDs lost content under text spacing. Converting decimal strings to Number also lost cents for large amounts. | Wrap identifiers and summary values, stack narrow summary cells, allow mobile amount wrapping, and provide a named, keyboard-focusable horizontal table scroller. Format integral digits with BigInt/Intl parts and retain the supplied decimal fraction and sign. No financial arithmetic, conversion or backend rounding changes. | 1.4.12 |
| A11Y-04 | Auth inputs lacked purpose metadata. | Name: `name`; login email identifier: `username`; registration address: `email`; passwords: `current-password` / `new-password`. Paste remains enabled. | 1.3.5 |
| A11Y-05 | API error extraction discarded Pydantic field locations. | Preserve only locations/messages in ApiError, never input/ctx. Associate auth field messages with stable IDs, aria-describedby and aria-invalid; focus the first invalid field; retain a single live summary and generic failures. Capture submitted credentials so password redaction remains correct after editing during an outstanding request. Preserve email/name; clear password after errors and successful registration. | 3.3.1; supporting error navigation |
| A11Y-06 | Queue wrapper referenced a missing heading; lazy panel skeleton labelled a generic div. | Remove redundant queue section semantics; retain the existing named queue panel. Give the temporary panel skeleton a real status role and textual loading message. | 4.1.2 |

## Draft and mutation policy

Unsaved decisions, reasons, notes and follow-up drafts are discarded on A → B, including returning B → A. A permission-boundary remount also discards drafts. Drafts remain local to the same case after an error/409 until selection changes. No draft persistence is added.

Switching does not cancel or redirect an already submitted server action. A late response updates/refetches only its original case cache. It cannot clear a newly mounted case's draft. Returning to A can show an action that completed while A was not selected. Failed/uncertain requests are never automatically retried as audited actions.

All mutation variables capture case identity and the observed revision at initiation. **API limitation:** existing PATCH and note contracts do not accept expected_revision. Their captured revision is context, not an optimistic-lock guarantee. Only follow-up and close send and enforce expected_revision. This batch does not extend backend contracts or claim stronger concurrency guarantees for PATCH/notes. Follow-up/close retain their existing authorization, revision and audit semantics.

## Compatibility and security review

Registration remains generic HTTP 202. Logout 204, 503, network failure, timeout, local-only clearing, valid-cookie restoration and retry semantics are unchanged. Backend refresh replay/family implementation is untouched. Browser tests use synthetic API routes and are not evidence of PostgreSQL/Redis integration.

Decimal display now retains exact supplied fractional digits, including values above Number.MAX_SAFE_INTEGER, negative zero and additional meaningful precision. Values are not abbreviated or converted. Existing malformed/noncanonical decimal strings are shown verbatim with their currency rather than converted to NaN. No changes were made to manual transaction currency defaults.

The test fixture previously failed to intercept `/cases/{id}/notes` while claiming to model note persistence. Its route now explicitly covers detail and notes; delayed-note tests assert the recorded note after leaving and returning, not just textarea contents or optimistic UI.

## RED evidence

- Initial auth/ARIA run reproduced absent autocomplete and unresolved `alert-queue-heading`. Its first case tests had an overly strict accessible-name selector and suite/teardown timeout; those harness failures are not counted as defect proof.
- After correcting the selector, all four initial case tests failed: decision `escalate` leaked into B; HTTP 409 caused no detail reread; pending A requests prevented normal B draft interaction.
- Contrast/spacing run: 5 failed. Placeholder measured 3.620992448756575:1; all four widths failed exact large-amount assertions.
- Focused submitted-password redaction test failed against the previous built UI when the password was edited during an outstanding request; rebuilt corrected UI passes.
- Test checkpoint: `fe7c3da` (new regressions). Intermediate GREEN attempts revealed TypeScript issues and test-fixture/selector problems; these were corrected rather than hidden or skipped.

## Commands and executed validation

All frontend commands ran from `frontend/`, using the committed package lock and existing installed toolchain. Playwright setup in PowerShell was `$env:PLAYWRIGHT_WEB_SERVER_COMMAND = 'npm run start -- -p 3101'`.

- `npm run lint`: PASS.
- `npm run typecheck`: PASS.
- `npm run build`: PASS on final application source.
- `npx playwright test --project=chromium --reporter=list --global-timeout=180000`: **71 passed, 1 existing skip, 0 failed**, final application source.
- `npx playwright test tests/e2e/accessibility tests/e2e/investigations tests/e2e/auth --project=firefox --project=webkit --reporter=list --global-timeout=240000`: **84 passed, 2 existing skips, 0 failed** before the final credential-snapshot hardening. That final change is covered by the subsequent cross-browser authentication run below.
- `npx playwright test tests/e2e/accessibility/batch1.spec.ts tests/e2e/accessibility/financial-spacing.spec.ts tests/e2e/accessibility/financial-display.spec.ts tests/e2e/investigations/draft-isolation.spec.ts tests/e2e/auth --project=mobile --project=iphone --project=tablet --reporter=list --global-timeout=240000`: **51 passed, 51 existing skips, 0 failed** before the final credential-snapshot hardening. Existing auth files intentionally skip mobile; new batch tests actually exercise auth and case selection at these profiles.
- `npx playwright test tests/e2e/accessibility/batch1.spec.ts tests/e2e/accessibility/financial-display.spec.ts tests/e2e/auth --project=firefox --project=webkit --project=mobile --project=iphone --project=tablet --reporter=list --global-timeout=240000`: **67 passed, 53 existing skips, 0 failed**, final application source. Includes the final submitted-password regression, exact display tests and loading status on all five profiles. No teardown errors.

The complete browser cross-product was not rerun. Counts above are distinct invocations, not unique-test totals. Existing Firefox/WebKit auth timeout tests are Chromium-only and remain skipped; deterministic clock-based case timeout tests ran on both engines. No new test skip was added.

Axe-core **4.14.0** was fetched into a temporary directory (`npm pack axe-core --pack-destination <temporary-directory>`), not added to package.json or the lockfile. A standalone Playwright probe injected axe.min.js and ran WCAG 2 A/AA, 2.1 A/AA and 2.2 AA tag checks against anonymous workspace, login, registration, field-validation errors, live case, copilot and upload. Final scan: **zero automatic violations in all seven states**; **one incomplete color-contrast check in live-case content** still needs human assessment. The scan first exposed the invalid skeleton label, which was fixed. It is not a full accessibility certification.

Computed CSS color/alpha tests run in the browser, not just token calculations. Normative line-height 1.5, paragraph margin 2em, letter spacing .12em and word spacing .16em were applied at **1440, 768, 375 and 320 CSS px** using a UUID and `-9999999999999999.99`. Tests check exact visible amount, detail-cell overflow and page overflow. Keyboard tests cover case selection and contained table scrolling. Exact-format regression examples also cover EUR sub-unit negatives, zero/negative zero, USD extra fractional precision and JPY integer values.

## Manual assessment and limitations

- Reviewed desktop/mobile full-page screenshots with normative text spacing using synthetic investigation data, including a full UUID and -9999999999999999.99. This is a visual inspection, not a baseline screenshot comparison or human assistive-technology test.
- Native browser 200% zoom: NOT VERIFIED. Viewport resizing and DPR emulation are not claimed as native zoom.
- Human screen-reader/password-manager testing: NOT VERIFIED. Autocomplete, semantic associations and focus are checked automatically.
- Axe live-case incomplete contrast item: manual verification remains required.
- Historical mobile/tablet teardown errors were not reproduced in the focused runs above; this does not resolve every historical full-matrix runner issue.
- No frontend coverage instrumentation was added; no percentage is claimed. Backend PostgreSQL/Redis tests were not rerun because backend behavior and contracts are unchanged.
- No GitHub CI success is inferred from local checks.
- Broader search/filtering, pagination, evidence APIs, document-Q&A redesign, cross-tab refresh synchronization and AWS deployment remain excluded.
- The separately tracked minimatch advisory is not closed or suppressed by this UX batch.

No full WCAG 2.2 AA conformance or production-readiness claim is made. Human accessibility review, relevant integration/release gates and actual PR CI remain separate requirements.
