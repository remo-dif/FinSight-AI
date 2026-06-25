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

const API_URL = process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");

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

async function refreshAccessToken(): Promise<string | null> {
  const response = await fetch(`${API_URL}/api/auth/refresh`, {
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
}

async function requestWithToken(path: string, init: ApiFetchInit | undefined, token: string | null) {
  const isFormData = init?.body instanceof FormData;
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {})
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
    throw new ApiError(formatApiError(response.status, detail, Boolean(token)), response.status);
  }
  if (response.status === 204) {
    return undefined as T;
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
    id: "CASE-1042",
    posted_at: "2026-05-28",
    merchant: "Card testing cluster",
    description: "First-seen device attempted six low-value authorizations in 11 minutes.",
    amount: "-184.22",
    currency: "USD",
    category: "Velocity spike",
    source: "rules"
  },
  {
    id: "CASE-1038",
    posted_at: "2026-05-26",
    merchant: "New beneficiary transfer",
    description: "High-value transfer to a beneficiary created from an unfamiliar IP range.",
    amount: "-4200.00",
    currency: "USD",
    category: "New payee",
    source: "model"
  },
  {
    id: "CASE-1031",
    posted_at: "2026-05-25",
    merchant: "Travel merchant mismatch",
    description: "Card-present transaction conflicts with recent customer session geography.",
    amount: "-611.99",
    currency: "USD",
    category: "Geo mismatch",
    source: "rules"
  }
];
