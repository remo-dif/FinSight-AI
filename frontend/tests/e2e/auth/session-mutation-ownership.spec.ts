import { expect, test } from "@playwright/test";
import { onlineManager, QueryClient } from "@tanstack/react-query";
import {
  addCaseNote, closeCase, logout, recordCaseFollowUp, restoreSession,
  sendChatMessage, updateCase, uploadFinancialFile
} from "@/lib/api";
import { useSessionStore } from "@/store/session";

const operations = {
  "document Q&A": (epoch: number) => sendChatMessage({
    mode: "document_qa", message: "Private question A", documentIds: ["private-document-a"]
  }, epoch),
  "case update": (epoch: number) => updateCase("private-case-a", { decision: "escalate", reason: "Private reason A" }, epoch),
  "case note": (epoch: number) => addCaseNote("private-case-a", "Private note A", epoch),
  "case follow-up": (epoch: number) => recordCaseFollowUp("private-case-a", {
    action: "escalation_outcome", reason: "Private outcome A", expected_revision: 2
  }, epoch),
  "case closure": (epoch: number) => closeCase("private-case-a", { reason: "Private closure A", expected_revision: 3 }, epoch),
  upload: (epoch: number) => uploadFinancialFile(new File(["Private CSV A"], "private-a.csv"), "EUR", epoch),
  logout: (epoch: number) => logout(epoch)
};

for (const [name, operation] of Object.entries(operations)) {
  test(`offline ${name} queued by A sends nothing after switching to B`, async () => {
    const client = new QueryClient();
    const originalFetch = globalThis.fetch;
    const previouslyOnline = onlineManager.isOnline();
    const sends: Array<{ path: string; authorization: string | null }> = [];
    client.mount();
    try {
      useSessionStore.getState().setAccessToken("synthetic-a");
      globalThis.fetch = async (input, init) => {
        sends.push({ path: String(input), authorization: new Headers(init?.headers).get("Authorization") });
        return name === "logout" ? new Response(null, { status: 204 }) : Response.json({});
      };
      onlineManager.setOnline(false);
      const mutation = client.getMutationCache().build(client, {
        mutationFn: async (epoch: number) => { await operation(epoch); }
      });
      const pending = mutation.execute(useSessionStore.getState().userDataEpoch).then(
        () => "completed", () => "rejected"
      );
      await expect.poll(() => mutation.state.isPaused).toBe(true);
      expect(sends).toEqual([]);
      useSessionStore.getState().clearSession();
      useSessionStore.getState().setAccessToken("synthetic-b");
      client.removeQueries();
      onlineManager.setOnline(true);
      const outcome = await pending;

      expect(sends).toEqual([]);
      expect(outcome).toBe("rejected");
      expect(useSessionStore.getState().accessToken).toBe("synthetic-b");
    } finally {
      client.unmount();
      client.clear();
      onlineManager.setOnline(previouslyOnline);
      globalThis.fetch = originalFetch;
      useSessionStore.getState().clearSession();
    }
  });
}

test("an offline mutation resumes with the rotated token of the same session", async () => {
  const client = new QueryClient();
  const originalFetch = globalThis.fetch;
  const previouslyOnline = onlineManager.isOnline();
  const sends: Array<{ authorization: string | null; body: BodyInit | null | undefined }> = [];
  client.mount();
  try {
    useSessionStore.getState().setAccessToken("synthetic-a");
    globalThis.fetch = async (input, init) => {
      if (String(input).endsWith("/refresh")) return Response.json({ access_token: "synthetic-a-rotated" });
      sends.push({ authorization: new Headers(init?.headers).get("Authorization"), body: init?.body });
      return Response.json({});
    };
    onlineManager.setOnline(false);
    const mutation = client.getMutationCache().build(client, { mutationFn: operations["document Q&A"] });
    const pending = mutation.execute(useSessionStore.getState().userDataEpoch);
    await expect.poll(() => mutation.state.isPaused).toBe(true);
    expect(await restoreSession()).toBe(true);
    onlineManager.setOnline(true);
    await pending;
    expect(sends).toHaveLength(1);
    expect(sends[0].authorization).toBe("Bearer synthetic-a-rotated");
    expect(JSON.parse(String(sends[0].body))).toMatchObject({
      message: "Private question A", document_ids: ["private-document-a"]
    });
  } finally {
    client.unmount();
    client.clear();
    onlineManager.setOnline(previouslyOnline);
    globalThis.fetch = originalFetch;
    useSessionStore.getState().clearSession();
  }
});
