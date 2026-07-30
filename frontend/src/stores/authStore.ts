import { create } from 'zustand';
import type { User } from '@/types';
import client from '@/api/client';

interface AuthState {
  token: string | null;
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  checkAuth: () => boolean;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('sq2_token'),
  user: (() => {
    try {
      const u = localStorage.getItem('sq2_user');
      return u ? JSON.parse(u) : null;
    } catch { return null; }
  })(),
  loading: false,

  login: async (username: string, password: string) => {
    set({ loading: true });
    try {
      const { data } = await client.post('/auth/login', { username, password });
      localStorage.setItem('sq2_token', data.access_token);
      localStorage.setItem('sq2_user', JSON.stringify(data.user));
      set({ token: data.access_token, user: data.user, loading: false });
    } catch (e) {
      set({ loading: false });
      throw e;
    }
  },

  logout: () => {
    localStorage.removeItem('sq2_token');
    localStorage.removeItem('sq2_user');
    set({ token: null, user: null });
  },

  checkAuth: () => !!localStorage.getItem('sq2_token'),
}));
