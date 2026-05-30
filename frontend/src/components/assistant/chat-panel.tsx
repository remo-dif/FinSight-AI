"use client";

import { useMutation } from "@tanstack/react-query";
import { LoaderCircle, Send, ShieldCheck } from "lucide-react";
import { FormEvent, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { sendChatMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSessionStore } from "@/store/session";

type Message = {
  role: "user" | "assistant";
  content: string;
  review?: string;
  tone?: "default" | "error";
};

export function ChatPanel() {
  const statusId = useId();
  const chatSessionId = useSessionStore((state) => state.chatSessionId);
  const setChatSessionId = useSessionStore((state) => state.setChatSessionId);
  const [input, setInput] = useState("Show my unusual spending this month");
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Ask about spending, budgets, recurring payments, merchants, or uploaded documents. Answers are grounded through approved tools."
      }
  ]);

  const chat = useMutation({
    mutationFn: sendChatMessage,
    onSuccess: (data) => {
      setChatSessionId(data.session_id);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer,
          review: data.review
        }
      ]);
    },
    onError: (error) => {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content:
            error instanceof Error
              ? error.message
              : "The assistant could not complete that request. Please try again.",
          tone: "error"
        }
      ]);
    }
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || chat.isPending) return;
    setMessages((current) => [...current, { role: "user", content: text }]);
    chat.mutate({ message: text, sessionId: chatSessionId });
    setInput("");
  }

  return (
    <Panel className="flex h-[540px] flex-col" aria-labelledby="assistant-heading">
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <div>
          <h2 id="assistant-heading" className="text-lg font-semibold">AI Financial Assistant</h2>
          <p className="mt-1 text-sm leading-5 text-muted">Tool-only analytics with reviewer validation</p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-success/10 text-success">
          <ShieldCheck aria-hidden className="h-5 w-5" />
        </span>
      </div>
      <div
        className="flex-1 space-y-3 overflow-y-auto py-4 pr-1"
        role="log"
        aria-live="polite"
        aria-label="Conversation messages"
      >
        {messages.map((message, index) => (
          <div
            key={`${message.role}-${index}`}
            role={message.tone === "error" ? "alert" : undefined}
            className={cn(
              "max-w-[85%] rounded-lg p-3 text-sm leading-6",
              message.role === "user"
                ? "ml-auto bg-accent text-white shadow-sm"
                : "border border-border bg-background",
              message.tone === "error" && "border-danger/40 bg-danger/5 text-danger"
            )}
          >
            {message.content}
            {message.review ? (
              <p className="mt-2 border-t border-border pt-2 text-xs leading-5 text-muted">
                Reviewer: {message.review}
              </p>
            ) : null}
          </div>
        ))}
        {chat.isPending ? (
          <div className="flex max-w-[85%] items-center gap-2 rounded-lg border border-border bg-background p-3 text-sm leading-6 text-muted" role="status">
            <LoaderCircle aria-hidden className="h-4 w-4 animate-spin text-accent" />
            Asking the finance tools...
          </div>
        ) : null}
      </div>
      <p id={statusId} className="sr-only" aria-live="assertive">
        {chat.isPending ? "The assistant is preparing an answer." : chat.isError ? "The last assistant request failed." : ""}
      </p>
      <form className="flex gap-2 border-t border-border pt-4" onSubmit={submit} aria-label="Send a message to the finance assistant">
        <input
          aria-label="Ask the finance assistant"
          aria-describedby={statusId}
          className="min-w-0 flex-1 rounded-md border border-border bg-white px-3 text-sm outline-none transition placeholder:text-muted/70 hover:border-accent/70 focus:border-accent focus:ring-2 focus:ring-accent/30"
          placeholder="Ask about spending, budgets, or merchants"
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <Button type="submit" aria-label="Send message" className="h-10 w-10 px-0" disabled={!input.trim() || chat.isPending}>
          {chat.isPending ? (
            <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Send aria-hidden className="h-4 w-4" />
          )}
        </Button>
      </form>
    </Panel>
  );
}
