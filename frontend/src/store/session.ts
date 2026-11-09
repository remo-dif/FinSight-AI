import { create } from "zustand";
import { persist } from "zustand/middleware";

type SessionState = {
  accessToken: string | null;
  sessionGeneration: number;
  userDataEpoch: number;
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
      userDataEpoch: 0,
      chatSessionId: null,
      // A login or clear changes ownership. A refresh fence alone does not.
      setAccessToken: (accessToken) => set(state => ({
        accessToken,
        chatSessionId: null,
        sessionGeneration: state.sessionGeneration + 1,
        userDataEpoch: state.userDataEpoch + 1
      })),
      clearSession: () => set(state => ({
        accessToken: null,
        chatSessionId: null,
        sessionGeneration: state.sessionGeneration + 1,
        userDataEpoch: state.userDataEpoch + (state.accessToken ? 1 : 0)
      })),
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
