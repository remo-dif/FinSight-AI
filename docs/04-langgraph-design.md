# 4. LangGraph Graph Design

## Graph

```mermaid
flowchart TD
  START --> Orchestrator
  Orchestrator --> Intent{"Intent"}
  Intent -->|transactions| TransactionAgent
  Intent -->|documents| DocumentAgent
  Intent -->|budget| BudgetPlannerAgent
  Intent -->|anomaly| AnomalyDetectionAgent
  Intent -->|recurring| RecurringPaymentAgent
  Intent -->|rag| RAGAgent
  Intent -->|report| ReportAgent
  TransactionAgent --> FinancialAnalystAgent
  BudgetPlannerAgent --> FinancialAnalystAgent
  AnomalyDetectionAgent --> FinancialAnalystAgent
  RecurringPaymentAgent --> FinancialAnalystAgent
  RAGAgent --> FinancialAnalystAgent
  DocumentAgent --> FinancialAnalystAgent
  FinancialAnalystAgent --> ReviewerAgent
  ReportAgent --> ReviewerAgent
  ReviewerAgent --> END
```

## Tool Policy

The LLM can request only these backend tools:

- `get_transactions`
- `get_monthly_summary`
- `compare_months`
- `get_spending_by_category`
- `detect_anomalies`
- `generate_budget`
- `get_top_merchants`
- `get_recurring_payments`

## Implementation Note

The backend exposes the graph through an adapter. In production, it can bind LangGraph nodes to OpenAI tool calls. In tests, deterministic node functions can run without external network calls.
