# Case dossier export

## Contents and scope

`GET /api/cases/{case_id}/dossier.pdf` and `.json` require the existing bearer-token authentication and transaction-owner check. Another owner's case and an unknown case both return 404, as case detail does. Closed cases remain readable. The exports include case state, transaction facts, applicable rule-based signals, account document metadata, notes, initial decision, follow-ups, and case audit events. They omit file bytes, extracted text, storage paths, unrelated users' data, generation time, exporting identity, and all `case.dossier_export_*` events from the canonical JSON. Export time and exporter name appear in the PDF as labeled, non-hashed metadata.

Documents are **not linked to cases** in the current schema. The evidence section is therefore the owner's account document library, explicitly labeled as such, and must not be interpreted as proof that a document supports this case. No migration or new storage subsystem is involved.

## Canonical JSON, version 1

The top-level object has `dossier_format_version`, `case`, `transaction`, `risk_signals`, `evidence_scope`, `evidence`, `notes`, `follow_ups`, and `audit_events`. Optional absent facts use JSON `null`; empty collections use `[]`. Object keys are sorted lexically. Notes, follow-ups, evidence, and audit events are ordered by creation timestamp and stable ID (follow-ups also include revision). Signal results are ordered by observation date, signal type, and signal ID. Text is normalized to Unicode NFC without trimming content. Monetary values are decimal strings retaining database precision and the original currency; binary floating-point values and non-finite decimals are rejected. Dates remain `YYYY-MM-DD`. Timestamps are UTC ISO 8601 with six fractional digits and `Z`; SQLite's timezone-naive test timestamps are interpreted as UTC. JSON is UTF-8 without BOM or insignificant whitespace. SHA-256 is computed over those exact response bytes, once, before the export audit write.

PostgreSQL reads use a single repeatable-read transaction after the authentication read transaction ends. It covers owner case/transaction state, all owner transactions needed to recompute signals, account uploads, notes, follow-ups, and audit events. The export audit insert is added after the snapshot and committed in that transaction. SQLite tests provide transaction-level checks but not the same concurrent snapshot guarantee. Export preparation can still fail after reading or before response delivery; the audit records server-side generation/response preparation, never browser receipt or saving.

Risk signals are recomputed with the current version-1 rules and fixed code thresholds from the owner's complete transaction history (up to 5,000 rows; over that limit, results are explicitly unavailable). The reference display limit is raised to 5,000 for the dossier, so an applicable case transaction is not omitted from a long signal cluster. The rules do not use the current clock. They depend on transactions outside the case, including later transactions and merchant/currency history; changes to that history or the rule implementation can change signal results and the hash. Existing case signal results are not persisted. Only signals whose returned references include the case transaction are shown. No missing explanation, threshold, or provenance is fabricated.

## Compare downloads

Download both formats for the same case and compare `X-Dossier-SHA256` headers. The PDF footer repeats the full digest on every page. You can independently hash the downloaded JSON bytes:

```bash
sha256sum case-CASE_UUID-dossier.json
```

The output must match the JSON response header and PDF footer. Separate downloads can differ if relevant facts change between requests; when digests differ, download both again. Hashing JSON and matching the footer verifies the JSON bytes against the digest displayed in the PDF. It does **not** independently verify the PDF's visible content, establish authenticity, authorship, or trusted creation time. Anyone able to modify both files can recalculate the digest. Digital signing and trusted timestamping are separate future work.

## Offline synthetic demo

After the README local setup and migrations, run `docker compose exec backend python -m scripts.seed_demo`. The command requires `APP_ENV=development` and `STORAGE_BACKEND=local`, creates only `synthetic-demo@finsight.invalid` and its missing synthetic rows, and refuses a colliding pre-existing account. Development-only password: `SyntheticDemo2026!`. Change or remove it before exposing any environment; never run this command against production. It uses fixed dates and RNG seed, creates 150 EUR spending transactions and corresponding cases through the existing transaction repository, and checks the four existing signal types. Repeat runs add no rows and do not alter unrelated data. It makes no OCR, LLM, storage-service, or other outbound calls. Synthetic PDFs are omitted because the ingestion pipeline would expand the seed to embedding/storage behavior and documents cannot yet be linked to cases.

`backend/tests/fixtures/synthetic_demo_import.csv` is a 24-row manual import example using the supported `date,merchant,amount,currency` headers, ISO dates, explicit EUR, and negative spending amounts. Upload it through the existing authenticated upload form. It contains duplicate, same-day velocity, unusual amount, and first-seen merchant examples. Duplicate and velocity can appear from this import alone; amount deviation and new-merchant status depend on preceding same-merchant/currency and general currency history. The full fixture includes such history, but importing into an account with other transactions may change the results. No rule thresholds are changed.

## Limitations

The hash is a content identifier, not a signature. Export events are excluded so repeated unchanged exports retain the same digest. Cross-owner review is not supported by the current authorization model, so a second user cannot lawfully export the same case to compare hashes. Existing account uploads have no case association. The generated PDF can differ byte-for-byte between exports because non-hashed exporter and generation metadata may change. Deployment status has not been verified.
