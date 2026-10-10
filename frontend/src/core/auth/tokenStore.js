/**
 * Credential holder.
 *
 * * Access token: memory only (never Web Storage → not readable by injected
 *   scripts after a reload; FE-04). A reload restores it via the httpOnly
 *   refresh cookie.
 * * Profile token: sessionStorage (per tab, survives reload; useless without
 *   the access token and bound to the same user server-side).
 */
const PROFILE_KEY = 'neotv.profile_token';
let access = null;
const listeners = new Set();

function readProfile() {
  try {
    return sessionStorage.getItem(PROFILE_KEY);
  } catch {
    return null;
  }
}

let profile = readProfile();

function emit() {
  for (const fn of listeners) fn();
}

export const tokenStore = {
  getAccess: () => access,
  setAccess(token) {
    access = token || null;
    emit();
  },
  getProfile: () => profile,
  setProfile(token) {
    profile = token || null;
    try {
      if (profile) sessionStorage.setItem(PROFILE_KEY, profile);
      else sessionStorage.removeItem(PROFILE_KEY);
    } catch {
      /* storage unavailable: keep in memory */
    }
    emit();
  },
  clear() {
    access = null;
    this.setProfile(null);
  },
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
