import { expect, test } from "@playwright/test";
import { useSessionStore } from "@/store/session";
import { apiFetch, logout, restoreSession } from "@/lib/api";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const tokens = (access_token: string) => Response.json({ access_token, refresh_token: "synthetic-refresh", token_type: "bearer" });
const originalFetch = globalThis.fetch;
test.afterEach(() => { globalThis.fetch = originalFetch; useSessionStore.getState().clearSession(); });

for (const result of ["401", "503", "network", "200"] as const) {
  test(`store ignores stale refresh ${result} after a new login`, async () => {
    useSessionStore.getState().clearSession();
    const gate = deferred<Response>();
    globalThis.fetch = async () => gate.promise;
    const pending = restoreSession();
    useSessionStore.getState().setAccessToken("new-login-token");
    if (result === "network") gate.reject(new Error("Synthetic network failure"));
    else gate.resolve(result === "200" ? tokens("old-session-token") : new Response(null, { status: Number(result) }));
    expect(await pending).toBe(false);
    expect(useSessionStore.getState().accessToken).toBe("new-login-token");
  });
}

test("clearing an already anonymous session invalidates an outstanding restoration", async () => {
  useSessionStore.getState().clearSession();
  const gate = deferred<Response>();
  globalThis.fetch = async () => gate.promise;
  const pending = restoreSession();
  useSessionStore.getState().clearSession();
  gate.resolve(tokens("must-not-resurrect"));
  expect(await pending).toBe(false);
  expect(useSessionStore.getState().accessToken).toBeNull();
});

test("normal rotations remain single-flight within the same session", async () => {
  useSessionStore.getState().setAccessToken("initial-token");
  const gate = deferred<Response>();
  let calls = 0;
  globalThis.fetch = async () => { calls++; return gate.promise; };
  const first = restoreSession(), second = restoreSession();
  expect(calls).toBe(1);
  gate.resolve(tokens("rotated-token"));
  expect(await Promise.all([first, second])).toEqual([true, true]);
  expect(useSessionStore.getState().accessToken).toBe("rotated-token");
});

test("an old flight cannot absorb or clear a newer session's refresh flight", async () => {
  useSessionStore.getState().clearSession();
  const old = deferred<Response>(), fresh = deferred<Response>();
  let calls = 0;
  globalThis.fetch = async () => (++calls === 1 ? old.promise : fresh.promise);
  const oldFlight = restoreSession();
  useSessionStore.getState().setAccessToken("new-login");
  const freshFlight = restoreSession();
  const separate = calls;
  old.resolve(new Response(null, { status: 401 }));
  await oldFlight;
  const joiningFresh = restoreSession();
  const coalesced = calls;
  fresh.resolve(tokens("new-session-rotation"));
  await Promise.all([freshFlight, joiningFresh]);
  expect(separate).toBe(2);
  expect(coalesced).toBe(2);
  expect(useSessionStore.getState().accessToken).toBe("new-session-rotation");
});

for (const status of [204, 503]) {
  test(`logout HTTP ${status} fences older refreshes without falsely clearing a failed logout`, async () => {
    useSessionStore.getState().setAccessToken("logged-in-token");
    const gate = deferred<Response>();
    globalThis.fetch = async input => String(input).endsWith("/refresh") ? gate.promise : new Response(null, { status });
    const pending = restoreSession();
    const result = await logout().then(() => "confirmed", () => "failed");
    if (status === 204) useSessionStore.getState().clearSession(); // Existing UI's confirmed-only clearing.
    gate.resolve(tokens("stale-before-logout"));
    await pending;
    expect(result).toBe(status === 204 ? "confirmed" : "failed");
    expect(useSessionStore.getState().accessToken).toBe(status === 204 ? null : "logged-in-token");
  });
}

test("an old protected action cannot be replayed with a different session's token", async () => {
  useSessionStore.getState().setAccessToken("account-A-token");
  const gate = deferred<Response>();
  let actions = 0, refreshes = 0;
  globalThis.fetch = async input => {
    if (String(input).endsWith("/refresh")) { refreshes++; return tokens("account-B-rotation"); }
    actions++;
    return actions === 1 ? gate.promise : Response.json({ saved: true });
  };
  const action = apiFetch("/api/synthetic-action", { method: "POST", requireAuth: true }).then(() => "accepted", () => "rejected");
  useSessionStore.getState().setAccessToken("account-B-token");
  gate.resolve(new Response(null, { status: 401 }));
  expect(await action).toBe("rejected");
  expect(actions).toBe(1);
  expect(refreshes).toBe(0);
});

test("a normal rotation does not invalidate an outstanding request in the same session", async () => {
  useSessionStore.getState().setAccessToken("same-session-initial");
  const gate = deferred<Response>();
  globalThis.fetch = async input => String(input).endsWith("/refresh") ? tokens("same-session-rotated") : gate.promise;
  const request = apiFetch<{ ok: boolean }>("/api/slow-read", { requireAuth: true });
  expect(await restoreSession()).toBe(true);
  gate.resolve(Response.json({ ok: true }));
  expect(await request).toEqual({ ok: true });
  expect(useSessionStore.getState().accessToken).toBe("same-session-rotated");
});

test("a late 401 reuses the same session's rotated token rather than rotating twice", async () => {
  useSessionStore.getState().setAccessToken("expired-token");
  const late = deferred<Response>();
  let refreshes = 0;
  globalThis.fetch = async (input, init) => {
    if (String(input).endsWith("/refresh")) { refreshes++; return tokens("already-rotated-token"); }
    if (new Headers(init?.headers).get("Authorization") === "Bearer already-rotated-token") return Response.json({ ok: true });
    return String(input).endsWith("/late") ? late.promise : new Response(null, { status: 401 });
  };
  const first = apiFetch("/api/first", { requireAuth: true });
  const second = apiFetch("/api/late", { requireAuth: true });
  await first;
  late.resolve(new Response(null, { status: 401 }));
  await second;
  expect(refreshes).toBe(1);
});


test("a refresh body that completes after login cannot overwrite the new token", async () => {
  useSessionStore.getState().clearSession();
  const body = deferred<{ access_token: string }>();
  const reading = deferred<void>();
  const response = new Response(null, { status: 200 });
  response.json = async () => { reading.resolve(); return body.promise; };
  globalThis.fetch = async () => response;
  const pending = restoreSession();
  await reading.promise;
  useSessionStore.getState().setAccessToken("new-login-after-headers");
  body.resolve({ access_token: "stale-body-token" });
  expect(await pending).toBe(false);
  expect(useSessionStore.getState().accessToken).toBe("new-login-after-headers");
});

test("protected response bodies are rejected if the session changes during decoding", async () => {
  useSessionStore.getState().setAccessToken("account-A");
  const body = deferred<{ privateData: string }>(), reading = deferred<void>();
  const response = new Response(null, { status: 200 });
  response.json = async () => { reading.resolve(); return body.promise; };
  globalThis.fetch = async () => response;
  const pending = apiFetch("/api/slow-body", { requireAuth: true }).then(() => "accepted", () => "rejected");
  await reading.promise;
  useSessionStore.getState().setAccessToken("account-B");
  body.resolve({ privateData: "synthetic-A-only" });
  expect(await pending).toBe("rejected");
});
