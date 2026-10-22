# Cycle 2.2 — CSV Data Integrity Fixes

Verdict: **PASS for the requested corrective scope**, not production readiness.
Baseline: `49896e9`. Final tested implementation: `d51e31f`.
No push, deployment, or Cycle 3 work was performed.

## Root causes and minimal corrections

### Missing or blank amounts became zero

Both `IngestionService.parse_csv` and `DocumentIngestionService.parse_csv` used
`raw.get("amount") or raw.get("Amount") or "0"`. Missing columns, omitted cells,
and empty cells therefore silently produced zero. Whitespace-only values failed
Decimal parsing but lacked an actionable missing-amount explanation.

Both parsers now check that the header contains `amount` or `Amount` before reading
records, including header-only files. Missing headers return HTTP 400 with guidance.
Per-record amount text must exist and contain a non-whitespace character before
categorization or monetary arithmetic. Missing/blank cells return HTTP 400 with the
physical location and instructions to provide the source amount. No numeric fallback
is used. Explicit `0`, positive, and negative values remain valid Decimal values.
Invalid/non-finite values retain controlled HTTP 400 behavior; existing precision
and finite-value checks are preserved.

Existing header aliases and their precedence remain unchanged: `amount` and `Amount`
are recognized; this is not general case/whitespace normalization for amount headers.
The change does not introduce duplicate-amount-header policy or refactor the parsers.

### Record counts were mislabeled as physical lines

`enumerate(reader, start=2)` counted CSV records instead of physical lines. Quoted
newlines or ignored blank lines made subsequent locations inaccurate.

Both parsers now iterate the same reader directly and use `reader.line_num` after
each record is read. The convention is **the ending physical line of the rejected
record**, including quoted multiline records. A first ordinary data record is still
line 2; a first record spanning lines 2–3 reports line 3. A subsequent invalid record
on physical line 5 (after an intervening blank line) reports line 5. This location is
passed to existing currency, date, amount, precision, and schema-validation errors.
Header-level errors identify the missing column rather than a transaction line.
Transaction text, ordering, currency, and amounts are not rewritten by line tracking.

## Atomic imports and compatibility

The existing route prepares and validates the entire CSV before storage finalization
and database persistence. No upload-route change was needed. New multipart API tests
send a valid multiline first record and a late invalid amount, verify HTTP 400 and
the ending physical line, and assert zero persisted transactions and upload records.
They also verify staging cleanup and preservation of a pre-existing file.

Cycle 2.1 explicit-currency resolution, optional `import_currency`, supported codes,
duplicate currency-header rejection, mixed currencies, and no-conversion policy are
unchanged. Existing currency, financial evidence, independent synthetic expectations,
authentication/user isolation, refunds/transfers/duplicates, and failure-path tests
remain green in the complete backend suite.

Intentional compatibility changes: CSVs lacking an accepted amount header or containing
missing/blank amounts now return HTTP 400 instead of importing invented zero values.
Empty files without an amount header now also return HTTP 400. Header-only files that
have an accepted amount header retain existing no-row handling. Error locations after
multiline records/blank lines now identify the ending physical line rather than a
record ordinal. Public response shapes, manual transaction API, frontend, rate limits,
refresh tokens, and transaction sign/Decimal semantics are unchanged.

## RED before GREEN — executed this cycle

User journeys: import genuine zero/signed amounts without altering data; reject absent
financial data without partial persistence; locate a rejected CSV record accurately.

| Checkpoint | Actual result |
| --- | --- |
| `61ab945` RED, tests only | New target executed against baseline production code: **50 failed, 14 passed**. Reproduced missing-header/cell acceptance, absent guidance, physical-line errors, and late-invalid upload handling. |
| `d51e31f` GREEN | Same target plus existing currency/non-finite/document/upload targets: **169 passed**. Final complete backend suite: **310 passed, 2 skipped**; Ruff passed. |

The new target contains 64 cases across both parsers and the upload endpoint. It covers
missing amount headers (with and without rows), omitted/empty/space/tab cells, both
header aliases, no categorization of missing amounts, explicit zero/signed values,
unchanged multiline text/order and mixed currencies, late invalid/non-finite values,
physical-line locations for currency/date/amount/precision/length errors, blank physical
lines, ending-line convention for the rejected multiline record, and atomic HTTP failure.

One first lint run reported test-only `Decimal("0")` style; it was changed to
`Decimal(0)` and final Ruff passed. No production failure was hidden or skipped.

### Commands actually executed

From `backend/`, after setting the following synthetic environment (no live services):

```powershell
$env:DATABASE_URL='sqlite+pysqlite:///:memory:'
$env:JWT_SECRET_KEY='cycle22-access-placeholder-123456789012'
$env:JWT_REFRESH_SECRET_KEY='cycle22-refresh-placeholder-123456789012'
$env:OPENAI_API_KEY='cycle22-placeholder-key'
$env:PYTHONDONTWRITEBYTECODE='1'

# RED before production edits: 50 failed, 14 passed.
../.venv/Scripts/python.exe -m pytest tests/test_cycle22_csv_integrity.py -q -p no:cacheprovider --tb=short

# GREEN: 169 passed.
../.venv/Scripts/python.exe -m pytest tests/test_cycle22_csv_integrity.py tests/test_cycle21_currency.py tests/test_cycle2_csv.py tests/test_document_ingestion.py tests/test_cycle2_uploads.py -q -p no:cacheprovider --tb=short

# Final: 310 passed, 0 failed, 2 skipped; 21 existing SQLAlchemy deprecation warnings.
../.venv/Scripts/python.exe -m coverage run --source=app -m pytest -q -p no:cacheprovider -o faulthandler_timeout=30 --tb=short
../.venv/Scripts/python.exe -m coverage report --precision=2 --fail-under=80
../.venv/Scripts/python.exe -m ruff check app tests --no-cache
```

Final statement coverage: **85.03%** (2491 statements, 373 missed), versus the prior
cycle's documented 84.95%. Ingestion service: 86.36%; document ingestion: 84.36%;
upload route and shared currency resolver: 100%. These are whole-module percentages,
not a claim that live provider or database paths were validated.

Also executed from the repository root: Ruff formatting on the new test file,
`git diff --check`, `git diff 49896e9 --check`, production diff/file-scope review,
and local RED/GREEN commits. All final whitespace checks passed.

Frontend build/lint/typecheck/browser suites were **not rerun in this cycle** because
no frontend changed. Earlier Cycle 2.1 results are historical, not Cycle 2.2 results.
No separate Python type checker, live provider/security dependency scanner, container
build, or deployment validation was run. Executed pytest imports exercised changed
Python modules successfully; this is not a substitute for independent static typing.

## Files changed

- `backend/app/services/ingestion.py`: amount presence checks; physical line tracking.
- `backend/app/services/document_ingestion.py`: identical validation/line convention.
- `backend/tests/test_cycle22_csv_integrity.py`: 64 new regression cases.
- `docs/21-cycle22-csv-integrity.md`: this evidence report.
- `docs/00-delivery-index.md`: link to the report.

## Remaining risks and deferred issues

- Two backend tests remain skipped: PostgreSQL/pgvector migration smoke needs
  `TEST_DATABASE_URL`; Redis integration needs `TEST_REDIS_URL`. API tests use ASGI
  transport and real SQLite transactions behind the existing async adapter, with
  authentication overridden. They do not independently prove token authorization or
  real asynchronous PostgreSQL behavior; existing authentication tests still pass.
- Manual transaction creation and the ORM retain the separately deferred implicit USD
  defaults. No manual API changes or historical data repairs were made.
- Historical zero-valued imports cannot safely be classified as genuine versus invented
  without source evidence. No existing records were rewritten.
- Existing general CSV limitations (including amount-header ambiguity and no-row-file
  policy beyond the required missing-header rejection) were not redesigned.
- Previously documented cross-system uncertain-acknowledgement/orphan and duplicate
  retry risks remain unchanged. Validation failures here occur before persistence.
- PostgreSQL/Redis, live-backend E2E, live S3/IAM, and production runtime validation
  remain release gates. Passing this correction cycle is not production readiness.
- No migrations, dependencies, authentication/rate-limit/token changes, frontend
  redesign, push, deployment, or Cycle 3 work were introduced.
