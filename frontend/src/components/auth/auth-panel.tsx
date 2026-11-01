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
    mutationFn: () => login(email, password),
    onSuccess: (data) => {
      queryClient.removeQueries({ queryKey: ["cases"] });
      queryClient.removeQueries({ queryKey: ["case"] });
      queryClient.removeQueries({ queryKey: uploadedDocumentsQueryKey });
      setAccessToken(data.access_token);
      announce("Signed in. Live finance tools are enabled.");
    },
    onError: (error) => announce(error instanceof Error ? error.message : "Sign in failed.", "alert")
  });

  const registerMutation = useMutation({
    mutationFn: () => register(email, password, fullName),
    onSuccess: (data) => {
      setMode("login");
      announce(data.message);
    },
    onError: (error) => announce(error instanceof Error ? error.message : "Registration failed.", "alert")
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
    if (mode === "login") {
      loginMutation.mutate();
    } else {
      registerMutation.mutate();
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
              onClick={() => setMode("login")}
              aria-pressed={mode === "login"}
            >
              Sign in
            </button>
            <button
              type="button"
              className={`rounded-md border px-3 py-2 text-sm font-semibold transition ${mode === "register" ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}
              onClick={() => setMode("register")}
              aria-pressed={mode === "register"}
            >
              Register
            </button>
          </div>
          {mode === "register" ? (
            <label className="block text-sm font-medium">
              Full name
              <input className="mt-1 h-10 w-full rounded-md border border-border px-3 text-sm" value={fullName} onChange={(event) => setFullName(event.target.value)} />
            </label>
          ) : null}
          <label className="block text-sm font-medium">
            Email
            <input className="mt-1 h-10 w-full rounded-md border border-border px-3 text-sm" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label className="block text-sm font-medium">
            Password
            <input className="mt-1 h-10 w-full rounded-md border border-border px-3 text-sm" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
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
