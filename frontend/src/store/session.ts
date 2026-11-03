import { create } from "zustand";
import { persist } from "zustand/middleware";

type SessionState = {
  accessToken: string | null;
  sessionGeneration: number;
  chatSessionId: string | null;
  setAccessToken: (accessToken: string | null) => void;
  clearSession: () => void;
  invalidateRefreshes: () => void;
  rotateAccessToken: (accessToken: string, generation: number) => boolean;
  setChatSessionId: (sessionId: string | null) => void;
};

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      accessToken: null,
      sessionGeneration: 0,
      chatSessionId: null,
      // Explicit login/replacement and clearing are fences, even null -> null.
      setAccessToken: (accessToken) => set(state => ({ accessToken, sessionGeneration: state.sessionGeneration + 1 })),
      clearSession: () => set(state => ({ accessToken: null, chatSessionId: null, sessionGeneration: state.sessionGeneration + 1 })),
      invalidateRefreshes: () => set(state => ({ sessionGeneration: state.sessionGeneration + 1 })),
      rotateAccessToken: (accessToken, generation) => {
        let applied = false;
        set(state => {
          if (state.sessionGeneration !== generation) return state;
          applied = true;
          // Rotation stays within the same session; outstanding reads remain valid.
          return { accessToken };
        });
        return applied;
      },
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
