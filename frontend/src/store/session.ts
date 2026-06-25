import { create } from "zustand";
import { persist } from "zustand/middleware";

type SessionState = {
  accessToken: string | null;
  chatSessionId: string | null;
  setAccessToken: (accessToken: string | null) => void;
  clearSession: () => void;
  setChatSessionId: (sessionId: string | null) => void;
};

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      accessToken: null,
      chatSessionId: null,
      setAccessToken: (accessToken) => set({ accessToken }),
      clearSession: () => set({ accessToken: null, chatSessionId: null }),
      setChatSessionId: (chatSessionId) => set({ chatSessionId })
    }),
    {
      name: "finsight-session",
      partialize: (state) => ({
        chatSessionId: state.chatSessionId
      })
    }
  )
);
