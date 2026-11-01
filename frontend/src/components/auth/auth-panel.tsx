"use client";

import { useMutation } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { LogIn, LogOut, UserPlus } from "lucide-react";
import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { ApiError, login, logout, register, uploadedDocumentsQueryKey } from "@/lib/api";
import { useSessionStore } from "@/store/session";

function logoutFailureMessage(error: unknown) {
  if (error instanceof ApiError && error.kind === "timeout") {
    return "Sign-out timed out. The server may have processed it, but revocation is unconfirmed. Retry sign out or clear only this browser session.";
  }
  if (error instanceof ApiError && error.kind === "network") {
    return "The sign-out request could not reach the server. Its outcome is unknown; your refresh session may remain active. Retry sign out or clear only this browser session.";
  }
  if (error instanceof ApiError && error.status === 401) {
    return "The server rejected sign out (HTTP 401). The refresh session may have expired or may remain active; revocation was not confirmed. Retry or clear this browser session, then sign in again.";
  }
  if (error instanceof ApiError && error.status !== undefined) {
    return `Sign-out failed (HTTP ${error.status}). Server-side revocation was not confirmed; your refresh session may remain active. Retry sign out or clear only this browser session.`;
  }
  return "Sign-out could not be confirmed. Your refresh session may remain active. Retry sign out or clear only this browser session.";
}

export function AuthPanel() {
  const queryClient = useQueryClient();
  const accessToken = useSessionStore((state) => state.accessToken);
  const setAccessToken = useSessionStore((state) => state.setAccessToken);
  const clearSession = useSessionStore((state) => state.clearSession);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("demo@example.com");
  const [password, setPassword] = useState("correct horse battery staple");
  const [fullName, setFullName] = useState("Demo User");
  const [message, setMessage] = useState<string | null>(null);
  const [messageRole, setMessageRole] = useState<"status" | "alert">("status");
  const [logoutFailed, setLogoutFailed] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function authenticationFailure(error: unknown, fallback: string, submittedPassword: string) {
    const redact = (text: string) => submittedPassword ? text.split(submittedPassword).join("[redacted]") : text;
    const errors: Record<string, string> = {};
    if (error instanceof ApiError) {
      for (const issue of error.validationIssues) {
        const [scope, field] = issue.location;
        if (scope === "body" && issue.location.length === 2 && typeof field === "string" &&
            ["email", "password", ...(mode === "register" ? ["full_name"] : [])].includes(field)) {
          errors[field] = [errors[field], redact(issue.message)].filter(Boolean).join(". ");
        }
      }
    }
    setFieldErrors(errors);
    announce(redact(error instanceof Error ? error.message : fallback), "alert");
    const first = ["full_name", "email", "password"].find(field => errors[field]);
    if (first) document.getElementById(`auth-${first}`)?.focus();
    setPassword("");
  }

  function switchMode(next: "login" | "register") {
    setMode(next);
    setFieldErrors({});
    announce(null);
  }

  function announce(nextMessage: string | null, role: "status" | "alert" = "status") {
    setMessage(nextMessage);
    setMessageRole(role);
  }

  function clearUserData() {
    queryClient.removeQueries({ queryKey: ["cases"] });
    queryClient.removeQueries({ queryKey: ["case"] });
    queryClient.removeQueries({ queryKey: uploadedDocumentsQueryKey });
    clearSession();
  }

  const loginMutation = useMutation({
    mutationFn: (credentials: { email: string; password: string }) => login(credentials.email, credentials.password),
    onSuccess: (data) => {
      queryClient.removeQueries({ queryKey: ["cases"] });
      queryClient.removeQueries({ queryKey: ["case"] });
      queryClient.removeQueries({ queryKey: uploadedDocumentsQueryKey });
      setAccessToken(data.access_token);
      announce("Signed in. Live finance tools are enabled.");
    },
    onError: (error, credentials) => authenticationFailure(error, "Sign in failed.", credentials.password)
  });

  const registerMutation = useMutation({
    mutationFn: (credentials: { email: string; password: string; fullName: string }) => register(credentials.email, credentials.password, credentials.fullName),
    onSuccess: (data) => {
      setMode("login");
      setFieldErrors({});
      setPassword("");
      announce(data.message);
    },
    onError: (error, credentials) => authenticationFailure(error, "Registration failed.", credentials.password)
  });

  const logoutMutation = useMutation({
    mutationFn: logout,
    onMutate: () => {
      setLogoutFailed(false);
      announce(null);
    },
    onSuccess: () => {
      clearUserData();
      setLogoutFailed(false);
      announce("Signed out. The server confirmed your session was revoked. Demo alerts are visible.");
    },
    onError: (error) => {
      setLogoutFailed(true);
      announce(logoutFailureMessage(error), "alert");
    }
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    announce(null);
    setFieldErrors({});
    if (mode === "login") {
      loginMutation.mutate({ email, password });
    } else {
      registerMutation.mutate({ email, password, fullName });
    }
  }

  return (
    <Panel as="section" className="p-4" aria-labelledby="auth-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="auth-heading" className="text-base font-semibold">Analyst session</h2>
          <p className="mt-1 text-sm text-muted">
            {accessToken ? "Live investigation data is active." : "Sign in to replace demo alerts with live data."}
          </p>
        </div>
        {accessToken ? (
          <Button
            type="button"
            className="h-9 px-3"
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
          >
            <LogOut aria-hidden className="h-4 w-4" />
            Sign out
          </Button>
        ) : null}
      </div>

      {logoutFailed ? (
        <Button
          type="button"
          className="mt-3 h-9 px-3"
          disabled={logoutMutation.isPending}
          onClick={() => {
            clearUserData();
            setLogoutFailed(false);
            announce(
              "Signed out on this device only. Server-side revocation was not confirmed; reloading may restore the server session.",
              "alert"
            );
          }}
        >
          Clear this device&apos;s session
        </Button>
      ) : null}

      {!accessToken ? (
        <form className="mt-4 space-y-3" onSubmit={submit}>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              className={`rounded-md border px-3 py-2 text-sm font-semibold transition ${mode === "login" ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}
              disabled={loginMutation.isPending || registerMutation.isPending}
              onClick={() => switchMode("login")}
              aria-pressed={mode === "login"}
            >
              Sign in
            </button>
            <button
              type="button"
              className={`rounded-md border px-3 py-2 text-sm font-semibold transition ${mode === "register" ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}
              disabled={loginMutation.isPending || registerMutation.isPending}
              onClick={() => switchMode("register")}
              aria-pressed={mode === "register"}
            >
              Register
            </button>
          </div>
          {[
            ...(mode === "register" ? [{ field: "full_name", label: "Full name", type: "text", purpose: "name", value: fullName, change: setFullName }] : []),
            { field: "email", label: "Email", type: "email", purpose: mode === "login" ? "username" : "email", value: email, change: setEmail },
            { field: "password", label: "Password", type: "password", purpose: mode === "login" ? "current-password" : "new-password", value: password, change: setPassword }
          ].map(({ field, label, type, purpose, value, change }) => (
            <div key={field}>
              <label className="block text-sm font-medium" htmlFor={`auth-${field}`}>{label}</label>
              <input
                id={`auth-${field}`} name={field} type={type} autoComplete={purpose}
                className="mt-1 min-h-10 w-full rounded-md border border-border px-3 py-2 text-sm"
                value={value} onChange={(event) => change(event.target.value)}
                aria-invalid={fieldErrors[field] ? true : undefined}
                aria-describedby={fieldErrors[field] ? `auth-${field}-error` : undefined}
              />
              {fieldErrors[field] ? <p id={`auth-${field}-error`} className="mt-1 text-sm text-danger">{fieldErrors[field]}</p> : null}
            </div>
          ))}
          <Button type="submit" disabled={loginMutation.isPending || registerMutation.isPending}>
            {mode === "login" ? <LogIn aria-hidden className="h-4 w-4" /> : <UserPlus aria-hidden className="h-4 w-4" />}
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>
      ) : null}

      {message ? (
        <p
          className={`mt-3 text-sm ${messageRole === "alert" ? "text-danger" : "text-muted"}`}
          role={messageRole}
          aria-live={messageRole === "alert" ? "assertive" : "polite"}
        >
          {message}
        </p>
      ) : null}
    </Panel>
  );
}
