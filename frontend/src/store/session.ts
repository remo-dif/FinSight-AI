import { create } from "zustand";

type SessionState = {
  accessToken: string | null;
  chatSessionId: string | null;
  setAccessToken: (token: string | null) => void;
  setChatSessionId: (sessionId: string | null) => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  accessToken: null,
  chatSessionId: null,
  setAccessToken: (accessToken) => set({ accessToken }),
  setChatSessionId: (chatSessionId) => set({ chatSessionId })
}));
