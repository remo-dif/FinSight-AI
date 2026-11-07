# PR5 real-model Document Q&A evaluation

PR5 is a manual experiment over the approved synthetic PR1 fixtures. It exercises PDF upload, PostgreSQL/pgvector retrieval and the authenticated `POST /api/documents/ask` route. The OpenAI SDK receives the actual application payload. The deterministic PR1–PR4 runners and baselines remain separate.

## Profile and offline planning

Use Python 3.12 and the existing backend dependencies. From the backend directory, run `python -m evaluation.real_model_runner plan --profile <profile.json>`. Planning uses the validated on-disk dataset, corpus and rubric. It does not initialize the application, network, database or provider clients.

A profile has `schema_version: 1`, `origin: "https://api.openai.com"`, `model`, `embedding_backend` and `embedding_model`. Remote embedding profiles use a `text-embedding-3-*` model and a positive `embedding_per_million` tariff. The local profile uses `deterministic-local-hash-v2` and omits that tariff. Both profiles require positive USD `input_per_million` and `output_per_million` rates, `pricing_source: "https://openai.com/api/pricing/"` and `pricing_date` as YYYY-MM-DD. Verify rates independently before a pilot. The runner does not fetch live pricing. Defaults are five repetitions, five retrieved results, minimum score 0.05 and a 30-second provider timeout.

Select a chat model compatible with the application's Chat Completions JSON mode, `temperature=0.0` and `max_tokens=450`. Confirm the effective deployment profile separately before describing any run as representative of it. With local embeddings, only the generation model is remote. This is a distinct experimental profile when the deployment uses remote embeddings.

## Opt-in and isolation

Provision an empty PostgreSQL database named `finsight_eval_*` on loopback, install pgvector, and use a dedicated role restricted to that database. Supply its URL in `FINSIGHT_EVAL_DATABASE_URL`. Supply a dedicated restricted project credential in `FINSIGHT_EVAL_OPENAI_API_KEY` using your secret manager. Keep both outside Git, shell transcripts and artifacts. The ASGI app uses synthetic principals and private temporary upload storage, with isolated SQLAlchemy sessions and a fresh schema per invocation. Only that schema and the run's temporary directory are cleaned up. A process kill can leave them behind. Use an ephemeral database and inspect ownership before any manual cleanup.

After explicit pilot approval and review of the offline plan, the manual interface is:

```sh
python -m evaluation.real_model_runner run --profile <path> --allow-paid \
  --max-requests <integer> --max-tokens <integer> \
  --max-estimated-cost <USD-decimal> --output <new-private-directory>

python -m evaluation.real_model_runner resume --run-dir <private-directory> --allow-paid
```

Use a private directory on a local filesystem outside the checkout. Protect it using OS permissions, including a restricted ACL on Windows. Run one process per directory. Never use a production URL or a tunnel to a production database. Planning over-reserves using corpus bytes and framing allowances. A conservative reservation can exceed anticipated real usage. Ingestion is once per run, authorized cases use repeated observations on the same index, and Q10/Q11 run once each. Temperature zero does not imply determinism or independence. Report per-case distributions with planned and completed denominators.

## Provider boundary and crash behavior

Dedicated sync and async HTTP transports allow HTTPS POST to the exact OpenAI origin and the expected embeddings or Chat Completions endpoint. Each phase checks its model and expected input. Ingestion uses chunks from hash-verified PDF fixtures. Query embeddings use the case question. Completion prompts are built by the application only after checking the owner, scope and persisted text of each chunk. Clients disable implicit retries, redirects and environment proxies. Q10 and Q11 must stop before retrieval and leave no provider attempts.

SQLite commits the reservation before transmission, then separately marks the attempt as uncertain before entering the HTTP transport. Journal version 2 records four attempt states.

| State | Meaning | Resume |
| --- | --- | --- |
| `reserved` | The reservation was committed before the transport was entered. | Blocks resume. |
| `uncertain` | The send was started or may have started, with no durable outcome. This includes network errors and a crash between sending and confirmation. | Blocks resume. |
| `confirmed` | The response passed the HTTP and usage checks. Missing usage is allowed and remains unknown. Validation and confirmation commit together. | Identical payloads can reuse the recorded response without a physical send. |
| `rejected` | A response was received but failed validation, including HTTP errors, malformed usage and `usage_exceeded_reservation`. | Blocks resume. |

When reported usage exceeds the token reservation, the journal atomically records the rejected state, the reported usage and the sanitized response envelope. It never marks this response reusable. The provider may already have billed the request. Every reservation remains in the request, token and cost totals, including missing usage and uncertain delivery. Error HTTP bodies are excluded from the journal. The transport uses request JSON bytes plus a framing allowance and the application's output cap to estimate tokens. Provider tokenization, pricing and billing adjustments can differ from the estimate.

The journal binds the profile, plan, checkout and ceilings. Version 1 journals cannot be resumed by version 2. Keep them for investigation. They are not migrated or reclassified. Resume skips terminal observations and preserves their original grades. A successful evaluation is an operationally complete observation, regardless of its answer-quality grade. A model reply that passed the transport checks but failed the application's answer parsing is a terminal operational failure. It cannot be retried within the same run and never counts as correct abstention. Other harness, authorization, provenance and unresolved provider errors are incomplete work and stop the run. A stored incomplete observation blocks resume. If interruption left no observation and every existing attempt is confirmed, resume may reconstruct the index and replay identical confirmed responses from the journal. Changed payloads are rejected.

Inspect an uncertain or rejected attempt using the journal's unit, endpoint, reservation, HTTP status or safe request ID when present. Reconcile possible charges with an authorized operator before considering a separately approved run. The tool provides no command to erase the reservation or retry that attempt. Seals detect accidental data changes. The journal and operator are trusted, so the seals are not signatures and the tool does not guarantee exactly-once delivery.

The version 2 summary lists planned units, terminal observations, successful evaluations, terminal operational failures, incomplete units (including missing observations), reserved, uncertain and rejected attempts, and confirmed responses reused during the current invocation. Exit code `0` means all planned observations completed without operational failure. Exit code `1` means all observations are terminal and at least one recorded an operational failure. Exit code `2` means the run was blocked, incomplete or invalid. A resume rejected during preflight leaves the existing artifacts intact.

## Grades and review

Retrieval uses PR2 span metrics on observed results. Required facts, the Q05 causal relationship, citation identity, citation support, abstention, Q08 conflict, authorization and operational reliability are separate dimensions. A syntactically valid reference can still lack relevant evidence. The evaluator uses response-level citations and checks their evidence geometry. Ordinary prose and semantic support that the rubric cannot establish go to `needs_review`. A provider or parsing failure never counts as correct abstention. For Q08, inspect the parsed draft independently of the public abstention. If either proposal was unavailable in the retrieved context, conflict reasoning is not fully observable.

Keep adjudications as separate versioned records keyed by observation digest and rubric digest. Record reviewer, dimension, verdict and reason. Review ambiguous judgments, Q05 and Q08, and a sample of automatic passes. The runner does not overwrite deterministic grades with human verdicts. It does not promote a baseline or apply a quality threshold.

## Artifacts and retention

The private run directory contains the digested `run_manifest.json`, `execution.sqlite3` journal, `observations.jsonl`, `grades.jsonl`, `adjudications.jsonl` and `summary.json`. Raw provider responses live in the journal, separately from parsed drafts and public responses. The journal stores returned model identifiers and safe request IDs when available. Credentials and authentication headers are excluded. Treat even synthetic-derived model output as untrusted and potentially sensitive. Apply a retention period, restrict access and delete private artifacts after review. The summary separates known usage from unknown attempts and records observation and grade file hashes.

Offline tests inject both simulated provider transports and use dummy credentials. The PostgreSQL integration test uses `FINSIGHT_TEST_PR5_DATABASE_URL` and fails closed on unexpected egress at the evaluation boundary. GitHub CI remains deterministic. Before a paid pilot, independently review the boundary, verify the deployment profile and model compatibility, approve a current tariff and ceilings, and verify database isolation and artifact retention. A paid pilot is separate from implementation verification.
