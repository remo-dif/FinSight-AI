# Cycle 2.1 — Explicit Currency Handling in CSV Imports

Baseline: `cf6c657`. Scope and policy approved by the user before implementation.
No push, deployment, database migration, dependency change, or historical-data rewrite.

## Root cause and affected paths

Both `IngestionService.parse_csv` and `DocumentIngestionService.parse_csv` used
`raw.get("currency") or raw.get("Currency") or "USD"`. Missing and blank currency
cells therefore became USD without source evidence. Three-letter unsupported codes
also passed the general transaction schema's format-only validation.

The live path is `POST /api/uploads` -> `prepare_upload` -> document CSV parser ->
storage finalization -> atomic database persistence. The older parser has no application
caller found but remains supported and tested. No documented bank-format currency
configuration was found. Neither the previous API nor UI accepted an import currency.

## Approved currency policy and API contract

`POST /api/uploads` accepts the existing multipart `file` and optional text field
`import_currency`. Response fields and authentication/authorization are unchanged.
The parameter applies only to CSV; existing PDF/image behavior is unchanged.

Supported codes reuse the reporting set: AUD, CAD, CHF, EUR, GBP, JPY, USD.
Codes must contain ASCII letters, are trimmed and normalized to uppercase, not converted. Other codes, symbols,
and malformed values return HTTP 400 with corrective guidance. No inferred bank format,
user locale, merchant, amount, or default currency is used.

| Row currency | Import selection | Result |
| --- | --- | --- |
| Explicit supported code | None | Preserve row currency |
| Missing/blank | Explicit supported code | Use selection |
| Missing/blank | None | Reject entire import with HTTP 400 and line number |
| Invalid/unsupported | Any | Reject; never substitute the selection |
| Explicit supported code | Same code | Accept |
| Explicit supported code | Different code | Reject conflict with HTTP 400 |
| Mixed supported codes | None | Preserve each row currency |

Currency header detection trims surrounding whitespace and ignores case. Two matching
headers are rejected before reading rows, including in header-only CSVs; values are
never chosen arbitrarily from duplicate columns. Other CSV schema/header behavior is
unchanged. A header-only/empty CSV still has no monetary transactions to resolve;
this cycle does not redesign empty-file handling.

Both parsers use `CsvCurrencyResolver`. Each returns a complete validated list or raises;
neither persists rows. Upload preparation validates the entire file before storage
publication or database writes. Thus a bad late row cannot partially import earlier rows.
The existing transaction/cleanup protections remain in place for persistence failures.
Non-finite monetary validation still runs before categorization; Decimal/sign/refund,
transfer, duplicate, and currency-isolation semantics are unchanged.

## Frontend and compatibility

The CSV-only selector starts at **Use currency column** with empty state. Selecting a
new file resets it. PDF/image uploads have no selector and send no currency selection.
Help text explains missing/blank cells, mixed-currency mode, matching explicit codes,
and the absence of currency conversion. Backend HTTP 400 guidance is displayed to users;
they can correct the selection and retry. No preselected USD/EUR is supplied.

Intentional compatibility change: currency-less CSVs formerly accepted as USD now fail
unless a caller explicitly supplies `import_currency`. Unsupported currency codes now
fail at import rather than becoming data that reporting cannot support. Valid supported
explicit-currency uploads remain compatible, including mixed-currency files without
selection. The general manual transaction API and response schemas are untouched.

Deploy the backend before the new frontend: an older backend ignores the new form field
and retains its unsafe USD behavior. No deployment was performed. Reverting this cycle
would reintroduce silent assumptions; disable affected CSV ingestion during such a
rollback rather than treating the baseline as financially safe. Previously misclassified
records cannot be identified or corrected reliably without original-source evidence;
no existing records were rewritten.

## Modified files

- `backend/app/services/import_currency.py`: shared resolver and actionable HTTP 400s.
- `backend/app/services/ingestion.py`: explicit currency resolution, no USD fallback.
- `backend/app/services/document_ingestion.py`: same resolver and preparation parameter.
- `backend/app/api/routes/uploads.py`: optional multipart parameter, same transaction lifecycle.
- `backend/tests/test_cycle21_currency.py`: dual-parser and real multipart API regressions.
- `backend/tests/test_document_ingestion.py`: existing persistence fixture now specifies EUR.
- `frontend/src/lib/api.ts`: optional selection added to FormData only when chosen.
- `frontend/src/components/uploads/upload-panel.tsx`: CSV-only selector/help/reset behavior.
- `frontend/tests/e2e/uploads/evidence.spec.ts`: behavioral browser regression.
- `docs/00-delivery-index.md` and this report: indexed policy and validation evidence.

## ECC red/green evidence

Journeys: import explicitly denominated statements unchanged; choose a known currency
when a statement omits it; correct ambiguous/invalid data without partial persistence;
preserve distinct currencies and another user's existing transactions.

| Checkpoint | Evidence |
| --- | --- |
| `af81870` backend RED | New currency target: 29 failed, 8 passed. Reproduced USD fallback, missing import parameter, unsupported codes, duplicate headers, and API acceptance of bad rows. |
| `16d4c20` backend GREEN | 92 targeted tests passed across currency, non-finite CSV, document ingestion, and upload failure targets. |
| `97b9e01` frontend RED | Chromium executed new browser test: missing CSV currency selector failed as intended. |
| `bc6265a` frontend GREEN | All 3 Chromium upload browser tests passed against local development server. |
| `43bf6df` extended regression | Added matching/blank-cell, missing-column, mixed-currency, unsupported-code, duplicate-header, and invalid-selection API cases. Full backend: 242 passed, 2 skipped. |
| `5778abe` normalization RED | Four new regressions reproduced Unicode long-s being normalized into USD, for row and import-level values in both parsers. |
| `63aea38` normalization GREEN | ASCII validation fixes all four cases. Final full backend: 246 passed, 2 skipped; 84.95% coverage; Ruff clean. |

The first frontend GREEN attempt exposed an overly broad test locator matching Next's
route announcer too. It was scoped to the Evidence ingestion region; all three tests
then passed. This was a test issue, not an application defect.

## Final validation

Backend commands, from `backend/`, with synthetic environment settings (in-memory
SQLite, placeholder signing keys/provider key, no live provider credentials):

```powershell
../.venv/Scripts/python.exe -m coverage run --source=app -m pytest -q -p no:cacheprovider -o faulthandler_timeout=30 --tb=short
../.venv/Scripts/python.exe -m coverage report --precision=2 --fail-under=80
../.venv/Scripts/python.exe -m ruff check app tests --no-cache
```

- Backend: **246 passed, 0 failed, 2 skipped**, 21 existing SQLAlchemy deprecation warnings.
- Statement coverage: **84.95%** (2479 statements, 373 missed), versus Cycle 2's 84.76%.
- Shared currency resolver: **100% statement coverage**; uploads route: **100%**.
- Backend Ruff: passed.
- `npm run lint`: passed.
- `npm run typecheck`: passed.
- `npm run build`: passed; generated optimized Next.js production output.
- Full configured browser matrix: **117 passed, 0 failed, 57 skipped** in 2.6 minutes.
  Chromium, Firefox, WebKit, Android/Pixel, iPhone and tablet projects ran against the
  optimized production build. The new currency workflow passed on all six projects.
  The 57 skips are existing viewport-specific exclusions (desktop behaviors omitted on
  mobile, mobile navigation omitted on desktop); no new test was skipped.
- `git diff --check`: passed; review found no migration/dependency/manual-API changes.

The 50 additional backend cases exercise both parsers and multipart HTTP requests using
ASGI transport, real SQLite transactions behind the async session adapter, and temporary
local storage. A valid first row plus invalid second row proves no partial transactions
or upload record persist; another user's existing transaction and a pre-existing file
remain unchanged. Duplicate-header rejection and explicit mixed currencies are also
exercised over HTTP. Existing independent synthetic-oracle and financial regressions pass.

Two backend tests remain skipped: PostgreSQL/pgvector migration smoke test needs
`TEST_DATABASE_URL`; Redis integration needs `TEST_REDIS_URL`. SQLite adapter results
are not real asynchronous PostgreSQL validation.

Frontend commands from `frontend/`: `npm run lint`, `npm run typecheck`, `npm run build`,
and `./node_modules/.bin/playwright.cmd test --reporter=list` with
`PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'` to use the built output.
The local server emitted the existing Next.js standalone-output warning: deployment
should use the standalone server artifact, not infer container/runtime validation from
this local `next start` run. Node also emitted a non-failing color-environment warning.
No standalone-container or live-service E2E validation was performed.

## Deferred risks and remaining release gates

- **Separate financial-correctness risk:** manual `POST /api/transactions` still uses
  `TransactionCreate.currency = "USD"` when omitted; the ORM also has a USD default.
  This cycle deliberately does not change that public API. A separate approved change
  must require explicit currency there and assess all consumers.
- Historical CSV records may already be incorrectly denominated. Currency normalization
  does not establish source authenticity or correct historical records.
- Currency support is limited to the seven reporting codes, with existing monetary
  scale rules unchanged. No conversion or new bank-format inference was added.
- Cycle 2 cross-system atomicity limitations persist: uncertain storage/commit
  acknowledgements can leave owned artifacts for manual reconciliation; response loss
  and a retried successful import are not guaranteed exactly-once. This is distinct
  from currency-validation failures, which occur before persistence.
- PostgreSQL/Redis integration and live S3/IAM checks remain mandatory release gates.
  Browser tests mock API responses and do not replace a live backend/database/storage
  end-to-end test. No production-readiness claim is made.
- No automated historical remediation, manual transaction API change, reconciliation
  worker, new dependency, migration, push, or deployment was performed.
