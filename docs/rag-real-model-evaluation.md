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

SQLite commits one reservation per physical request before transmission. Budget totals include all reservations, including responses whose usage was absent or delivery uncertain. The transport reserves request JSON byte length plus a framing allowance as input tokens and the application's output cap for generation. Estimated spend applies the supplied rates to that reservation. If returned usage exceeds the reservation, the run stops. Local accounting limits additional requests. Provider tokenization, billing adjustments, pricing changes and unknown delivery prevent a guarantee of an exact billed amount. Timeouts apply to provider HTTP operations.

The journal binds the profile, plan, checkout and ceilings. Resume skips completed observations and can reconstruct the isolated index from confirmed responses for identical request payloads. A reservation without a safely persisted response blocks resume. This also applies to non-success HTTP responses in this version. Reconcile such a run separately. The tool does not delete a reservation, automatically retry an uncertain request or promise exactly-once delivery at the provider. Seals detect accidental data changes. The local journal and its operator are trusted, so the seals are not signatures.

## Grades and review

Retrieval uses PR2 span metrics on observed results. Required facts, the Q05 causal relationship, citation identity, citation support, abstention, Q08 conflict, authorization and operational reliability are separate dimensions. A syntactically valid reference can still lack relevant evidence. The evaluator uses response-level citations and checks their evidence geometry. Ordinary prose and semantic support that the rubric cannot establish go to `needs_review`. A provider or parsing failure never counts as correct abstention. For Q08, inspect the parsed draft independently of the public abstention. If either proposal was unavailable in the retrieved context, conflict reasoning is not fully observable.

Keep adjudications as separate versioned records keyed by observation digest and rubric digest. Record reviewer, dimension, verdict and reason. Review ambiguous judgments, Q05 and Q08, and a sample of automatic passes. The runner does not overwrite deterministic grades with human verdicts. It does not promote a baseline or apply a quality threshold.

## Artifacts and retention

The private run directory contains the digested `run_manifest.json`, `execution.sqlite3` journal, `observations.jsonl`, `grades.jsonl`, `adjudications.jsonl` and `summary.json`. Raw provider responses live in the journal, separately from parsed drafts and public responses. The journal stores returned model identifiers and safe request IDs when available. Credentials and authentication headers are excluded. Treat even synthetic-derived model output as untrusted and potentially sensitive. Apply a retention period, restrict access and delete private artifacts after review. The summary separates known usage from unknown attempts and records observation and grade file hashes.

Offline tests inject both simulated provider transports and use dummy credentials. The PostgreSQL integration test uses `FINSIGHT_TEST_PR5_DATABASE_URL` and fails closed on unexpected egress at the evaluation boundary. GitHub CI remains deterministic. Before a paid pilot, independently review the boundary, verify the deployment profile and model compatibility, approve a current tariff and ceilings, and verify database isolation and artifact retention. A paid pilot is separate from implementation verification.
