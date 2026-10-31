# 3. Multi-Agent Architecture

## Supervisor Pattern

The implemented LangGraph flow is supervisor -> one financial specialist -> reviewer. Application keyword rules choose the specialist; the LLM does not select tools or route work. This is a bounded graph, not a set of independently acting agents.

## Agents

- Orchestrator/supervisor: resolves intent, currency and supported reporting periods.
- Summary specialist: monthly transaction summaries and two-month comparisons.
- Category specialist: category spending.
- Merchant specialist: top-merchant spending.
- Budget specialist: all-history spending-based estimates.
- Anomaly specialist: unusual-amount heuristics.
- Recurring specialist: repeated-charge estimates; verified subscription cadence is not guaranteed.
- Reviewer: validates the canonical financial evidence and renders permitted facts deterministically.

RAG retrieval is a service call before graph execution, not a separate graph agent. Although retrieved chunks enter `AgentState`, the financial `_evidence` generation path sends claim IDs rather than document excerpts to the LLM. Document question answering, document citations and dedicated document/report agents remain planned. Categorization currently belongs to an ingestion service, not an independent agent.

## Routing Contract

All agent communication passes through `AgentState`:

- `user_id`
- `message`
- `intent`
- `tool_results`
- `agent_outputs`
- `review`
- `final_answer`

## Reviewer Gate

Every public financial chat response passes the reviewer. It checks:

- Tool results match the canonical calculation snapshot.
- Currency, reporting period, amounts, totals and transaction references are consistent.
- Selected claim IDs are complete and supported; invalid selections use a deterministic explanation, while invalid evidence is rejected.

This gate does not validate arbitrary document claims, document citations, general professional advice or every possible sensitive-data disclosure. The model has no direct SQL/database tool. User isolation is enforced by authenticated, user-scoped application queries rather than by a reviewer promise.
