"use client";

import { useMutation } from "@tanstack/react-query";
import { LogIn, LogOut, UserPlus } from "lucide-react";
import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { login, register } from "@/lib/api";
import { useSessionStore } from "@/store/session";

export function AuthPanel() {
  const accessToken = useSessionStore((state) => state.accessToken);
  const setTokens = useSessionStore((state) => state.setTokens);
  const clearSession = useSessionStore((state) => state.clearSession);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("demo@example.com");
  const [password, setPassword] = useState("correct horse battery staple");
  const [fullName, setFullName] = useState("Demo User");
  const [message, setMessage] = useState<string | null>(null);

  const loginMutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      setMessage("Signed in. Live finance tools are enabled.");
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "Sign in failed.")
  });

  const registerMutation = useMutation({
    mutationFn: () => register(email, password, fullName),
    onSuccess: () => {
      setMode("login");
      setMessage("Account created. Sign in to enable live data.");
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "Registration failed.")
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (mode === "login") {
      loginMutation.mutate();
    } else {
      registerMutation.mutate();
    }
  }

  return (
    <Panel aria-labelledby="auth-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="auth-heading" className="text-lg font-semibold">Account</h2>
          <p className="mt-1 text-sm text-muted">
            {accessToken ? "Live API access is active." : "Sign in to replace demo data with your own."}
          </p>
        </div>
        {accessToken ? (
          <Button type="button" className="h-9 px-3" onClick={clearSession}>
            <LogOut aria-hidden className="h-4 w-4" />
            Sign out
          </Button>
        ) : null}
      </div>

      {!accessToken ? (
        <form className="mt-4 space-y-3" onSubmit={submit}>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              className={`rounded-md border px-3 py-2 text-sm font-semibold transition ${mode === "login" ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}
              onClick={() => setMode("login")}
            >
              Sign in
            </button>
            <button
              type="button"
              className={`rounded-md border px-3 py-2 text-sm font-semibold transition ${mode === "register" ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}
              onClick={() => setMode("register")}
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

      {message ? <p className="mt-3 text-sm text-muted" role="status">{message}</p> : null}
    </Panel>
  );
}
