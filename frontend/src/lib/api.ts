import { useSessionStore } from "@/store/session";

export type MonthlySummary = {
  month: string;
  income: string;
  spending: string;
  net_cash_flow: string;
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

export type ChatResponse = {
  session_id: string;
  answer: string;
  review: string;
  tool_results: Record<string, unknown>;
};

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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function formatApiError(status: number, fallback: string, hasToken: boolean) {
  if ((status === 401 || status === 403) && !hasToken) {
    return "Authentication is required before using live finance tools. Sign in or provide a valid session token, then try again.";
  }
  if (status === 401 || status === 403) {
    return "Your session token was rejected. Sign in again or refresh the token, then try again.";
  }
  return fallback;
}

function extractErrorMessage(body: unknown, fallback: string) {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map(String).join(", ");
  }
  return fallback;
}

export async function apiFetch<T>(path: string, init?: ApiFetchInit): Promise<T> {
  const token = useSessionStore.getState().accessToken;
  if (init?.requireAuth && !token) {
    throw new ApiError(
      "Authentication is required before using live finance tools. Sign in or provide a valid session token, then try again.",
      401
    );
  }

  const isFormData = init?.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {})
      }
    });
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
    throw new ApiError(formatApiError(response.status, detail, Boolean(token)), response.status);
  }
  return response.json() as Promise<T>;
}

export type ChatRequest = {
  message: string;
  sessionId?: string | null;
};

export function sendChatMessage({ message, sessionId }: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: sessionId ?? null
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

export function fetchMonthlySummary(month: string): Promise<MonthlySummary> {
  return apiFetch<MonthlySummary>(`/api/transactions/summary/${month}`, { requireAuth: true });
}

export function fetchTransactions(limit = 50): Promise<Transaction[]> {
  return apiFetch<Transaction[]>(`/api/transactions?limit=${limit}`, { requireAuth: true });
}

export type UploadResponse = {
  file_id: string;
  status: string;
  imported: number;
  indexed: number;
};

export function uploadFinancialFile(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<UploadResponse>("/api/uploads", {
    method: "POST",
    body,
    requireAuth: true
  });
}

export const demoTransactions: Transaction[] = [
  {
    id: "1",
    posted_at: "2026-05-28",
    merchant: "Whole Foods",
    description: "Groceries",
    amount: "-84.22",
    currency: "USD",
    category: "Groceries",
    source: "demo"
  },
  {
    id: "2",
    posted_at: "2026-05-26",
    merchant: "Payroll",
    description: "Salary",
    amount: "4200.00",
    currency: "USD",
    category: "Income",
    source: "demo"
  },
  {
    id: "3",
    posted_at: "2026-05-25",
    merchant: "Spotify",
    description: "Monthly plan",
    amount: "-11.99",
    currency: "USD",
    category: "Subscriptions",
    source: "demo"
  }
];
