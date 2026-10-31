import { useSessionStore } from "@/store/session";

export type MonthlySummary = {
  month: string;
  income: string;
  spending: string;
  net_cash_flow: string;
  currency?: string | null;
};

export type Transaction = {
  id: string;
  posted_at: string;
  merchant: string;
  description: string;
  amount: string;
  currency: string;
  category: string;
  source: string;
};

export type CaseStatus = "new" | "needs_evidence" | "escalated" | "resolved";
export type CaseDecision = "escalate" | "request_verification" | "false_positive";

export type InvestigationCase = Transaction & {
  status: CaseStatus;
  assignee_name: string | null;
  assigned_to_me: boolean;
  decision: CaseDecision | null;
  decision_reason: string | null;
  updated_at: string | null;
};

export type CaseNote = {
  id: string;
  author_name: string;
  content: string;
  created_at: string;
};

export type CaseDetail = InvestigationCase & { notes: CaseNote[] };

export type CaseUpdate = {
  status?: CaseStatus;
  assignee?: "me" | "unassigned";
  decision?: CaseDecision;
  reason?: string;
};

export const caseListQueryKey = (limit = 50) => ["cases", limit] as const;
export const caseDetailQueryKey = (caseId: string) => ["case", caseId] as const;

export type ChatResponse = {
  session_id: string | null;
  answer: string;
  review: string;
  tool_results: Record<string, unknown>;
  citations?: Array<{
    id: string;
    document_id: string;
    document_name: string;
    chunk_id: string;
    chunk_index?: number | null;
    page?: number | null;
    excerpt: string;
    score?: number | null;
    reference: string;
  }>;
  sources?: Array<{
    id: string;
    document_id: string;
    document_name: string;
    chunk_id: string;
    chunk_index?: number | null;
    page?: number | null;
    excerpt: string;
    score?: number | null;
    reference: string;
  }>;
  grounded?: boolean;
  abstained?: boolean;
  status?: "ok" | "abstained" | "provider_error" | "insufficient_evidence" | "extractive_preview";
  grounding_note?: string | null;
};

export type DocumentCitation = NonNullable<ChatResponse["citations"]>[number];

export type DocumentQuestionRequest = {
  question?: string;
  document_ids?: string[] | null;
  document_scope?: string[] | null;
  limit?: number;
  min_score?: number | null;
};

export type DocumentQuestionResponse = {
  answer: string;
  citations: DocumentCitation[];
  sources: DocumentCitation[];
  grounded: boolean;
  abstained: boolean;
  document_ids: string[];
  status: "ok" | "abstained" | "provider_error" | "insufficient_evidence" | "extractive_preview";
  grounding_note: string;
};

export type UploadedDocument = {
  id: string;
  filename: string;
  status: string;
  created_at: string;
};

export const uploadedDocumentsQueryKey = ["uploaded-documents"] as const;

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type UserResponse = {
  id: string;
  email: string;
  full_name: string;
  role: string;
};

type ApiFetchInit = RequestInit & {
  requireAuth?: boolean;
};

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");
const API_REQUEST_TIMEOUT_MS = 10_000;
let refreshRequest: Promise<string | null> | null = null;

function formatApiError(status: number, fallback: string, hasToken: boolean, requiresAuth: boolean) {
  if ((status === 401 || status === 403) && requiresAuth && !hasToken) {
    return "Authentication is required before using live finance tools. Sign in or provide a valid session token, then try again.";
  }
  if (status === 401 && hasToken) {
    return "Your session token was rejected. Sign in again or refresh the token, then try again.";
  }
  return fallback;
}

function extractErrorMessage(body: unknown, fallback: string) {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map((item: unknown) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") {
          return item.msg;
        }
        return "";
      }).filter((message) => message.trim().length > 0);
      return messages.length ? messages.join(", ") : fallback;
    }
  }
  return fallback;
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);
  const abortRequest = () => controller.abort();

  init.signal?.addEventListener("abort", abortRequest, { once: true });
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abortRequest);
  }
}

async function performTokenRefresh(): Promise<string | null> {
  try {
    const response = await fetchWithTimeout(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({})
    });
    if (!response.ok) {
      useSessionStore.getState().clearSession();
      return null;
    }

    const data = (await response.json()) as TokenResponse;
    useSessionStore.getState().setAccessToken(data.access_token);
    return data.access_token;
  } catch {
    useSessionStore.getState().clearSession();
    return null;
  }
}

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshRequest) {
    refreshRequest = performTokenRefresh().finally(() => {
      refreshRequest = null;
    });
  }
  return refreshRequest;
}

export async function restoreSession(): Promise<boolean> {
  return Boolean(await refreshAccessToken());
}

async function requestWithToken(path: string, init: ApiFetchInit | undefined, token: string | null) {
  const requestInit = { ...(init ?? {}) };
  delete requestInit.requireAuth;
  const isFormData = requestInit.body instanceof FormData;
  return fetchWithTimeout(`${API_URL}${path}`, {
    ...requestInit,
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(requestInit.headers ?? {})
    }
  });
}

export async function apiFetch<T>(path: string, init?: ApiFetchInit): Promise<T> {
  let token = useSessionStore.getState().accessToken;
  if (init?.requireAuth && !token) {
    token = await refreshAccessToken();
  }
  if (init?.requireAuth && !token) {
    throw new ApiError(
      "Authentication is required before using live finance tools. Sign in or provide a valid session token, then try again.",
      401
    );
  }

  let response: Response;
  try {
    response = await requestWithToken(path, init, token);
    if (response.status === 401 && token) {
      const refreshedToken = await refreshAccessToken();
      if (refreshedToken) {
        response = await requestWithToken(path, init, refreshedToken);
      }
    }
  } catch {
    throw new ApiError("Unable to reach the finance API. Check that the backend is running, then try again.");
  }

  if (!response.ok) {
    let detail = `API request failed: ${response.status}`;
    try {
      const body = await response.json();
      detail = extractErrorMessage(body, detail);
    } catch {
      // Keep the status-only fallback when the server does not return JSON.
    }
    throw new ApiError(formatApiError(response.status, detail, Boolean(token), Boolean(init?.requireAuth)), response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export type ChatRequest = {
  message: string;
  sessionId?: string | null;
  mode?: "finance" | "document_qa";
  documentIds?: string[];
};

export function sendChatMessage({
  message,
  sessionId,
  mode = "finance",
  documentIds
}: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: sessionId ?? null,
      mode,
      ...(mode === "document_qa" ? { document_ids: documentIds ?? null } : {})
    }),
    requireAuth: true
  });
}

export function fetchUploadedDocuments(offset = 0, limit = 100): Promise<UploadedDocument[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<UploadedDocument[]>(`/api/uploads?${query}`, { requireAuth: true });
}

export function askDocumentQuestion(
  question: string,
  documentIds?: string[] | null,
  options?: { limit?: number; minScore?: number | null }
): Promise<DocumentQuestionResponse> {
  return apiFetch<DocumentQuestionResponse>("/api/documents/ask", {
    method: "POST",
    body: JSON.stringify({
      question,
      document_ids: documentIds ?? null,
      limit: options?.limit ?? 5,
      min_score: options?.minScore ?? null
    }),
    requireAuth: true
  });
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export function register(email: string, password: string, fullName: string): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName })
  });
}

export function refreshSession(refreshToken: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken })
  });
}

export async function logout(): Promise<void> {
  await apiFetch<void>("/api/auth/logout", {
    method: "POST",
    body: JSON.stringify({})
  });
}

export function fetchMonthlySummary(month: string): Promise<MonthlySummary> {
  return apiFetch<MonthlySummary>(`/api/transactions/summary/${month}`, { requireAuth: true });
}

export function fetchTransactions(limit = 50): Promise<Transaction[]> {
  return apiFetch<Transaction[]>(`/api/transactions?limit=${limit}`, { requireAuth: true });
}

export function fetchCases(limit = 50): Promise<InvestigationCase[]> {
  return apiFetch<InvestigationCase[]>(`/api/cases?limit=${limit}`, { requireAuth: true });
}

export function fetchCaseDetail(caseId: string): Promise<CaseDetail> {
  return apiFetch<CaseDetail>(`/api/cases/${caseId}`, { requireAuth: true });
}

export function updateCase(caseId: string, update: CaseUpdate): Promise<InvestigationCase> {
  return apiFetch<InvestigationCase>(`/api/cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(update),
    requireAuth: true
  });
}

export function addCaseNote(caseId: string, content: string): Promise<CaseNote> {
  return apiFetch<CaseNote>(`/api/cases/${caseId}/notes`, {
    method: "POST",
    body: JSON.stringify({ content }),
    requireAuth: true
  });
}

export type UploadResponse = {
  file_id: string;
  status: string;
  imported: number;
  indexed: number;
};

export function uploadFinancialFile(file: File, importCurrency?: string): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", file);
  if (importCurrency) body.append("import_currency", importCurrency);
  return apiFetch<UploadResponse>("/api/uploads", {
    method: "POST",
    body,
    requireAuth: true
  });
}

export const demoTransactions: InvestigationCase[] = [
  {
    id: "CASE-1042",
    posted_at: "2026-05-28",
    merchant: "Card testing cluster",
    description: "First-seen device attempted six low-value authorizations in 11 minutes.",
    amount: "-184.22",
    currency: "USD",
    category: "Velocity spike",
    source: "rules",
    status: "needs_evidence",
    assignee_name: null,
    assigned_to_me: false,
    decision: null,
    decision_reason: null,
    updated_at: null
  },
  {
    id: "CASE-1038",
    posted_at: "2026-05-26",
    merchant: "New beneficiary transfer",
    description: "High-value transfer to a beneficiary created from an unfamiliar IP range.",
    amount: "-4200.00",
    currency: "USD",
    category: "New payee",
    source: "model",
    status: "escalated",
    assignee_name: "Risk Ops",
    assigned_to_me: false,
    decision: null,
    decision_reason: null,
    updated_at: null
  },
  {
    id: "CASE-1031",
    posted_at: "2026-05-25",
    merchant: "Travel merchant mismatch",
    description: "Card-present transaction conflicts with recent customer session geography.",
    amount: "-611.99",
    currency: "USD",
    category: "Geo mismatch",
    source: "rules",
    status: "new",
    assignee_name: null,
    assigned_to_me: false,
    decision: null,
    decision_reason: null,
    updated_at: null
  }
];
