/**
 * Single source of truth for "who is signed in" (FE-01: exactly one provider,
 * mounted once by the app shell).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { tokenStore } from './tokenStore';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState({ status: 'loading', user: null });

  const adopt = useCallback((session) => {
    tokenStore.setAccess(session.access_token);
    setState({ status: 'authenticated', user: session.user });
    return session.user;
  }, []);

  const dropLocal = useCallback(() => {
    tokenStore.clear();
    queryClient.clear();
    setState({ status: 'anonymous', user: null });
  }, [queryClient]);

  // Restore the session after a reload from the httpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false;
    api
      .refresh()
      .then((session) => !cancelled && adopt(session))
      .catch(() => !cancelled && setState({ status: 'anonymous', user: null }));
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  useEffect(() => {
    const onLogout = () => dropLocal();
    window.addEventListener('auth:logout', onLogout);
    return () => window.removeEventListener('auth:logout', onLogout);
  }, [dropLocal]);

  const login = useCallback(
    async (username, password) => adopt(await api.call('identity_login', { body: { username, password } })),
    [adopt],
  );

  const register = useCallback(
    async ({ username, email, password }) => {
      await api.call('identity_register', { body: { username, email: email || null, password } });
      return login(username, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await api.call('identity_logout');
    } finally {
      dropLocal();
    }
  }, [dropLocal]);

  const logoutEverywhere = useCallback(async () => {
    try {
      await api.call('identity_logout_all');
    } finally {
      dropLocal();
    }
  }, [dropLocal]);

  const changePassword = useCallback(
    async (currentPassword, newPassword) =>
      adopt(
        await api.call('identity_change_password', {
          body: { current_password: currentPassword, new_password: newPassword },
        }),
      ),
    [adopt],
  );

  /** Re-read /me (e.g. after e-mail verification) without touching tokens. */
  const reloadUser = useCallback(async () => {
    const user = await api.call('identity_me');
    setState((s) => (s.status === 'authenticated' ? { ...s, user } : s));
    return user;
  }, []);

  /** Forget the local session only (server already revoked it, e.g. after a password reset). */
  const forgetSession = useCallback(() => dropLocal(), [dropLocal]);

  const value = useMemo(() => {
    const permissions = new Set(state.user?.permissions ?? []);
    return {
      ...state,
      isAuthenticated: state.status === 'authenticated',
      can: (permission) => permissions.has('*') || permissions.has(permission),
      login,
      register,
      logout,
      logoutEverywhere,
      changePassword,
      reloadUser,
      forgetSession,
    };
  }, [state, login, register, logout, logoutEverywhere, changePassword, reloadUser, forgetSession]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth() outside <AuthProvider>');
  return ctx;
}
