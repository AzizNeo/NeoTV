/**
 * Current viewer profile. The selected profile travels as `X-Profile-Token`
 * (set by the API client from tokenStore); switching profiles clears every
 * cached query so one profile never sees another's library.
 */
import { createContext, useCallback, useContext, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { tokenStore } from '@/core/auth/tokenStore';

const ProfileContext = createContext(null);
export const profileKeys = { list: ['profiles', 'list'], current: ['profiles', 'current'] };

export function ProfileProvider({ children }) {
  const { isAuthenticated } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const profiles = useQuery({
    queryKey: profileKeys.list,
    queryFn: () => api.call('profile_list_profiles'),
    enabled: isAuthenticated,
  });
  const current = useQuery({
    queryKey: profileKeys.current,
    queryFn: () => api.call('profile_get_current'),
    enabled: isAuthenticated,
  });

  // Several profiles and none chosen in this tab → ask "who is watching?" once.
  useEffect(() => {
    if (!isAuthenticated || !profiles.data || tokenStore.getProfile()) return;
    if (profiles.data.length > 1 && !window.location.pathname.startsWith('/profiles')) navigate('/profiles');
  }, [isAuthenticated, profiles.data, navigate]);

  useEffect(() => {
    const onReselect = () => navigate('/profiles');
    window.addEventListener('profile:reselect', onReselect);
    return () => window.removeEventListener('profile:reselect', onReselect);
  }, [navigate]);

  const select = useCallback(
    async (profileId, pin) => {
      const result = await api.call('profile_select_profile', {
        params: { profile_id: profileId },
        body: pin ? { pin } : {},
      });
      tokenStore.setProfile(result.profile_token);
      await queryClient.resetQueries(); // everything below is profile-scoped
      return result.profile;
    },
    [queryClient],
  );

  const value = useMemo(
    () => ({
      profiles: profiles.data ?? [],
      current: current.data ?? null,
      isLoading: profiles.isLoading || current.isLoading,
      select,
      refresh: () => queryClient.invalidateQueries({ queryKey: ['profiles'] }),
    }),
    [profiles.data, profiles.isLoading, current.data, current.isLoading, select, queryClient],
  );
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>;
}

export function useProfile() {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error('useProfile() outside <ProfileProvider>');
  return ctx;
}
