"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "@/i18n/context";

export function LoadingStatus() {
  const t = useTranslations();
  const [message, setMessage] = useState("");

  useEffect(() => {
    const announcement = window.setTimeout(() => {
      setMessage(`${t("loadingWorkspace")}.`);
    }, 100);

    return () => window.clearTimeout(announcement);
  }, [t]);

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
