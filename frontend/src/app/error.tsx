"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <section className="w-full max-w-lg rounded-lg border border-border bg-panel p-6 text-center shadow-soft" aria-labelledby="route-error-heading">
        <p className="text-xs font-semibold uppercase tracking-wide text-danger">Workspace unavailable</p>
        <h1 id="route-error-heading" className="mt-2 text-xl font-semibold">We could not load this investigation view.</h1>
        <p className="mt-2 text-sm text-muted">Your current work is unchanged. Retry the route when you are ready.</p>
        <button type="button" className="mt-5 h-10 rounded-md bg-accent px-4 font-semibold text-white" onClick={reset}>
          Try again
        </button>
      </section>
    </main>
  );
}
