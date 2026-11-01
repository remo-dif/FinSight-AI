# Issue #14 — Accessibility Verification and Authentication Coverage

Status: automated checks completed; manual screen-reader and native 200% zoom verification remains **NOT VERIFIED**. Issue #14 should remain open. This report does not claim WCAG 2.2 AA conformance or production readiness.

## Baseline and tested source

- Merged UX/WCAG Batch 1: PR #13, commit `3bf27dc7c098b3bda41315d529a0b3ba54c1b39a`.
- Branch base: latest `origin/master` fetched for this work, `57defd4401ba7ace882e0da9bf5ff54e9ba54cf0`.
- Branch: `fix/issue-14-accessibility-verification`.
- Tested implementation commit: `cca64027290b4e1d64e84a6169ac899d749b1e9c`. The full matrix ran on the exact source tree recorded by this commit; no code changes followed the run.
- The test data and authentication responses described below are deterministic Playwright mocks; no backend, production service, or AWS resource was accessed or changed.
- The requested ECC-specific accessibility, frontend-a11y, browser-qa, security-review, and testing skill labels were not available in the active skill catalog for this session. No ECC installation or configuration was changed; verification used the existing Batch 1 report, repository tests, and axe-core.

## Findings and changes

### axe-core contrast result

The test reproduces an authenticated live-case queue at a 1280 × 720 CSS-pixel viewport. axe-core 4.14.0 reports the following four nodes as `color-contrast` **incomplete**, not violations:

| axe selector | Relevant HTML | Computed foreground | Effective background | Calculated ratio |
|---|---|---|---|---:|
| `.cursor-pointer:nth-child(1) > .text-right` | `<td class="break-all px-3 py-3 text-right font-semibold">-$7,400.00</td>` | `rgb(22, 27, 39)` | `rgb(231.4, 238.6, 244.5)` | 14.770992:1 |
| `.cursor-pointer:nth-child(1) > .break-words` | `<td class="break-words px-3 py-3">Needs evidence</td>` | `rgb(22, 27, 39)` | `rgb(231.4, 238.6, 244.5)` | 14.770992:1 |
| `.cursor-pointer:nth-child(2) > .text-right` | `<td class="break-all px-3 py-3 text-right font-semibold">-$92.13</td>` | `rgb(22, 27, 39)` | `rgb(255, 255, 255)` | 17.210512:1 |
| `.cursor-pointer:nth-child(2) > .break-words` | `<td class="break-words px-3 py-3">New</td>` | `rgb(22, 27, 39)` | `rgb(255, 255, 255)` | 17.210512:1 |

The first row has a transparent cell over `rgba(19, 91, 150, 0.1)` on a white panel; compositing gives `(231.4, 238.6, 244.5)`. The second row is white. All targets are 14px text, so WCAG 2.2 SC 1.4.3 (AA) requires at least 4.5:1. The calculated ratios exceed that threshold.

axe's reported `contrastRatio: 0` is a sentinel for an unresolved sample, not a measured zero-contrast value. Its message is “Element's background color could not be determined because it's partially obscured by another element.” At `scrollLeft: 0`, the queue is horizontally scrollable (`scrollWidth: 720`, `clientWidth: 414`, `overflow-x: auto`); the center hit lands on adjacent detail-panel content (`dt`/`dd`), outside the target cell. Scrolling the queue changes which offscreen cells are marked incomplete.

**Conclusion:** this is a valid automated result that axe cannot conclusively classify, not a confirmed contrast violation and not a PASS. The computed style compositing is encouraging but does not replace visual inspection/pixel evidence of the rendered cells and selected-row state. Manual inspection remains required. In the final Chromium scan, the settled live-case state had 4 incomplete contrast nodes; after scrolling to the end, 10 different nodes were incomplete and the original four were no longer reported. Browser: Playwright Chromium 148.0.7778.96; Playwright 1.60.0; axe-core pinned to 4.14.0.

The rerun through the repository's existing Next `next start` test-server path produced zero axe violations across the scanned workspace states. Next prints a warning because the app uses standalone output, but the server serves the built page/styles and the configured tests complete. Incomplete findings are retained and reported rather than converted to PASS. An earlier direct standalone-server attempt produced layout-dependent target-size findings and suite timeouts; it is not treated as product evidence.

### Manual contrast inspection — NOT VERIFIED

1. Use the local test server and synthetic live-case fixture. Record the tested commit, OS, browser/version, viewport/window dimensions, and actual zoom level.
2. Set the browser to 100% zoom and a 1280 × 720 CSS-pixel viewport. Sign in through the deterministic mock, select the first live case, and record the queue's horizontal scroll position.
3. Use the queue's own horizontal scrollbar or keyboard scrolling to bring each of the four listed cells fully into view. Capture a screenshot for each visible selected/unselected row state; do not infer a color for a cell while it is obscured or offscreen.
4. In browser developer tools, record the target's computed text color/font size and each ancestor's background color, opacity, image, and blend behavior. Include the selected-row alpha layer and its panel background.
5. From a screenshot of the fully visible target, record the effective background sample using a documented pixel/color sampler; calculate the WCAG contrast ratio from the foreground and background values with a documented contrast calculator. Keep the unaltered screenshot and the sampled coordinates/values.
6. Report one result per selector, including row selection state, effective colors, ratio, 4.5:1 AA threshold, screenshot filename, and any overlap. If the target cannot be isolated, retain the result as unresolved rather than PASS.

### Confirmed defect and regression fix

The drawer focus-restoration regression exposed by WebKit was fixed. The workspace now retains the actual activating element from the trigger event and restores focus to that trigger after close, rather than relying on `document.activeElement` after the drawer mounts. Automated tests cover the drawer name, focus containment, focus restoration, and visible keyboard focus.

### Mobile authentication coverage

Current auth-only execution covers 108 cases across Chromium, Firefox, WebKit, Pixel 7, iPhone 15, and iPad Pro 11: **78 PASS, 30 SKIP, 0 FAIL**. All three emulated mobile profiles execute eight authentication UI cases each:

- Successful logout with the mocked HTTP 204 response and UI confirmation.
- HTTP 503 logout failure, preserving the session and not claiming revocation.
- Network failure, uncertain revocation, and explicit local-only cleanup.
- Session restoration after reload when the mocked refresh session remains valid.
- Generic HTTP 202 registration for both new and existing-account scenarios.
- Keyboard/touch interaction with authentication controls.
- Accessible field-level 422 validation assertions are also exercised by the mobile accessibility regression test.

Responses are mocked at the browser network boundary; these tests verify frontend behavior, not backend integration. Security Hardening V2 refresh replay protection, authorization, and audited mutation contracts were not changed.

Skip inventory:

| Inventory | Before Issue #14 work | Current |
|---|---:|---:|
| Authentication skips across Pixel, iPhone, and iPad profiles | 51 (17/profile, as reported by Issue #14) | 30 (10/profile) |
| Firefox/WebKit desktop timeout exclusions | 2 | 0 |
| Other skips in the complete focused matrix | not part of the 51-auth count | 3 (desktop keyboard-navigation test excluded on the three touch profiles) |

The remaining mobile auth skips are the five comprehensive validation-response variants and five additional session/retry/token edge cases in each mobile profile. They remain covered on desktop; the mobile suite exercises the shared authentication UI, a structured field-level error, 204/503/network logout outcomes, local clearing, refresh-session restoration, 202 registration, and keyboard/touch controls. This is a deliberate viewport-coverage boundary, not a claim that every desktop scenario has been duplicated on mobile. The full focused matrix has 33 skips total: 30 auth skips plus the three touch-profile keyboard-navigation exclusions.

The former Firefox/WebKit timeout exclusions were removed only after testing the Playwright-clock scenario. The clock is installed after login and advances only the application timeout. Firefox and WebKit each passed three repeated runs (6/6); the cross-profile auth run also passes the timeout case in all six projects. No timeout test is skipped in the current source.

## Automated verification

All commands ran from `frontend/` on Windows 11 Pro (build 26300). The Playwright projects use Chromium 148.0.7778.96, Firefox 150.0.2, and WebKit 26.4; mobile profiles are Playwright device emulation, not physical-device testing.

| Command/check | Result |
|---|---|
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e -- tests/e2e/auth --project=chromium --project=firefox --project=webkit --project=mobile --project=iphone --project=tablet --workers=2 --reporter=list` | 78 PASS, 30 SKIP, 0 FAIL (108 total) |
| `npm run test:e2e -- tests/e2e/accessibility/axe.spec.ts --project=chromium --reporter=list --global-timeout=240000` | 1 PASS; zero axe violations; live-case contrast remains incomplete as described above |
| `npm run test:e2e -- tests/e2e/investigations/draft-isolation.spec.ts --project=webkit --grep 'a delayed successful note stays on A' --repeat-each=3 --workers=1 --reporter=list` | 3 PASS |
| `npm run test:e2e -- tests/e2e/auth/session.spec.ts --project=firefox --project=webkit --grep 'logout timeout is reported as an unknown server outcome' --repeat-each=3 --workers=2 --reporter=list` | 6 PASS (three each on Firefox and WebKit) |
| Focused cross-browser matrix (Batch 1, axe, financial display/spacing, workspace, draft isolation, and auth; Chromium/Firefox/WebKit/Pixel/iPhone/iPad) | 213 PASS, 33 SKIP, 0 FAIL (246 total; 5.6 minutes) |
| `git diff --check` | PASS |

The focused matrix covers case A/B draft isolation, accessible authentication validation, autocomplete, placeholder and essential-input contrast, WCAG text-spacing overrides, exact financial amounts/identifiers, drawer behavior, keyboard focus, responsive layouts, and axe scans. It runs Chromium, Firefox, WebKit, and the supported emulated mobile profiles.

Two earlier two-worker matrix attempts each reported 212 PASS, 1 FAIL, and 33 SKIP; the sole failure was the same WebKit note-submit case where the “Add note” button remained disabled after filling. The test now explicitly waits for the controlled field value and enabled state; the isolated WebKit scenario passed three repetitions. The final serial full matrix passed all 213 runnable tests. A separate pre-fix serial run with `--global-timeout=600000` reported 213 PASS and 33 SKIP but also emitted suite/teardown timeout errors at the 600-second cap, so it is not counted as a clean run.

The test server command used for the final matrix was set in PowerShell as:

```powershell
$env:PLAYWRIGHT_WEB_SERVER_COMMAND = 'node node_modules/next/dist/bin/next start -p 3101'
```

The full matrix command was:

```powershell
npm run test:e2e -- tests/e2e/accessibility/batch1.spec.ts tests/e2e/accessibility/axe.spec.ts tests/e2e/accessibility/financial-display.spec.ts tests/e2e/accessibility/financial-spacing.spec.ts tests/e2e/accessibility/workspace.spec.ts tests/e2e/investigations/draft-isolation.spec.ts tests/e2e/auth --project=chromium --project=firefox --project=webkit --project=mobile --project=iphone --project=tablet --workers=1 --reporter=list
```

## Manual screen-reader verification — NOT VERIFIED

No real screen reader was used. DOM/ARIA assertions are not a substitute. Run the following with synthetic data; record the exact OS, browser and assistive-technology versions, tested commit, and outcomes.

### NVDA with Firefox or Chrome

1. Start the local application with synthetic data; do not use production accounts or data. Record OS/browser/NVDA versions and display/window dimensions.
2. Use landmark navigation (`D`) and heading navigation (`H`) to traverse the workspace. Confirm the page has understandable landmarks and a logical heading sequence.
3. Tab to **Sign in**, open the drawer, and confirm the announced name is “Analyst session.” Tab and Shift+Tab through its controls; verify focus remains within the open drawer. Close it and verify focus returns to **Sign in**.
4. Repeat for the Copilot and upload drawers. Confirm their accessible names, close controls, focus containment, and focus restoration.
5. In a local deterministic mock, return a structured HTTP 422 field error. Confirm each field is announced with its label and associated error, the first invalid field receives focus, and the summary is useful without echoing passwords or API input/context.
6. Exercise loading, saving, successful completion, HTTP failure, and network failure. Confirm status/error announcements are timely and understandable.
7. Type distinct drafts on case A, switch to case B by keyboard, and verify B has no A draft. Submit a delayed A action, type a B draft, then release the response; confirm the result remains associated with A and B's draft remains unchanged.
8. Record each outcome and any defect; do not infer a pass from the accessibility tree.

### VoiceOver with Safari (if available)

Repeat the same scenarios using VoiceOver navigation and rotor. Record the actual macOS/Safari/VoiceOver versions. If that environment is unavailable, leave this section NOT VERIFIED rather than substituting another browser.

Evidence to attach: dated notes and screenshots only where useful; screenshots do not replace spoken-output observations.

## Native browser zoom at 200% — NOT VERIFIED

No native browser zoom was exercised. Playwright viewport resizing, device-scale-factor emulation, and screenshots at a smaller viewport are not native zoom evidence.

1. Use a local run with synthetic cases and record the tested commit, OS edition/build, browser/version, physical display resolution, and browser window dimensions.
2. Set actual browser zoom to **200%** using the browser's View/Zoom controls. Do not resize the viewport or change device pixel ratio to simulate zoom.
3. Capture screenshots and inspect the case queue, selected-case detail, session drawer, Copilot, and upload interface.
4. Verify long UUIDs, full signed monetary amounts, signs, currency units, and decimal precision remain available without clipping or lossy abbreviation.
5. Tab to the horizontally scrollable queue/table. Verify keyboard scrolling is available, the focus indicator remains visible, and the intended container—not the whole page unexpectedly—scrolls.
6. Trigger validation errors and failed operations. Verify error messages remain visible, associated with their fields, and reachable without overlap.
7. Record each result, screenshot filename, browser/OS/window metadata, and any issue. Leave unperformed checks NOT VERIFIED.

Required evidence is currently outstanding: actual browser zoom at 200%, screenshots from each requested interface, and manual outcomes.

## Remaining Issue #14 work and risks

- Complete and record real NVDA/Firefox-or-Chrome checks; complete VoiceOver/Safari if available.
- Complete actual native 200% zoom checks with browser/OS/window metadata and screenshots.
- Manually inspect the incomplete live-case contrast nodes while each target is visible; retain visual/pixel evidence and a final reviewer conclusion. Do not reclassify axe's incomplete result as PASS.
- Review the remaining mobile skip boundary during independent review. There are currently no non-Chromium desktop timeout exclusions.
- An earlier dependency-install audit summary reported 13 moderate findings, and GitHub reported one moderate Dependabot vulnerability on the default branch during push. Neither was analyzed or remediated as part of this focused accessibility task.
- Keep Issue #14 open until required manual evidence and coverage decisions are recorded. No full WCAG conformance or production-readiness claim is made.
