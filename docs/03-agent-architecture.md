# 3. Multi-Agent Architecture

## Supervisor Pattern

The application uses a hierarchical agent architecture. The Orchestrator Agent is the only component allowed to route work. Agents do not call each other directly.

## Agents

- Orchestrator Agent: routes user intent and merges outputs.
- Transaction Agent: answers transaction lookup and merchant questions.
- Document Agent: extracts and summarizes uploaded files.
- Categorization Agent: assigns and improves transaction categories.
- Financial Analyst Agent: performs spending and cash-flow analysis.
- Budget Planner Agent: generates budget recommendations.
- Anomaly Detection Agent: identifies unusual transactions.
- Recurring Payment Agent: detects subscriptions and repeating payments.
- RAG Agent: retrieves personal document context from pgvector.
- Report Agent: creates user-ready summaries.
- Reviewer Agent: checks financial reasoning, missing context, safety, and unsupported claims.

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

No AI response is returned until the Reviewer Agent validates:

- The answer is based on tool output or retrieved context.
- No hidden SQL/database access was requested.
- Financial advice is framed as analysis, not certified professional advice.
- Sensitive data is not unnecessarily echoed.
