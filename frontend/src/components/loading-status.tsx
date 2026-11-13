"use client";

import { useEffect, useState } from "react";

export function LoadingStatus() {
  const [message, setMessage] = useState("");

  useEffect(() => {
    const announcement = window.setTimeout(() => {
      setMessage("Loading investigation workspace.");
    }, 100);

    return () => window.clearTimeout(announcement);
  }, []);

  return (
    <p
      id="workspace-loading-status"
      className="sr-only"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {message}
    </p>
  );
}
