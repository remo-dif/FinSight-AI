import { createServer } from "node:http";

createServer((request, response) => {
  response.setHeader("Content-Type", "application/json");
  if (request.url === "/") return response.end("{}");
  if (request.url !== "/api/cases?limit=50" || request.headers.authorization !== "Bearer synthetic-a") {
    response.statusCode = 401;
    return response.end("{}");
  }
  response.end(JSON.stringify([{
    id: "CASE-SSR-A", merchant: "Synthetic SSR A", posted_at: "2026-06-18",
    description: "Synthetic case", amount: "1.00", currency: "EUR", category: "Test",
    source: "rules", status: "new", assignee_name: null, assigned_to_me: false,
    decision: null, decision_reason: null, updated_at: null
  }]));
}).listen(3102, "127.0.0.1");
