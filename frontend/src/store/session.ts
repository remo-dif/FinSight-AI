import { create } from "zustand";
import { persist } from "zustand/middleware";

type SessionState = {
  accessToken: string | null;
  refreshToken: string | null;
  chatSessionId: string | null;
  setTokens: (accessToken: string | null, refreshToken: string | null) => void;
  clearSession: () => void;
  setChatSessionId: (sessionId: string | null) => void;
};

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      chatSessionId: null,
      setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),
      clearSession: () => set({ accessToken: null, refreshToken: null, chatSessionId: null }),
      setChatSessionId: (chatSessionId) => set({ chatSessionId })
    }),
    {
      name: "finsight-session",
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        chatSessionId: state.chatSessionId
      })
    }
  )
);
