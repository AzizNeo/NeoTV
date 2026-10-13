import { useCallback, useState } from 'react';

const MAX = 6;
const keyFor = (scope) => `neotv.recentSearches.${scope}`;

function read(scope) {
  try {
    const list = JSON.parse(localStorage.getItem(keyFor(scope)) ?? '[]');
    return Array.isArray(list) ? list.filter((s) => typeof s === 'string').slice(0, MAX) : [];
  } catch {
    return []; // blocked or corrupt storage: start empty, never break the page
  }
}

function write(scope, list) {
  try {
    localStorage.setItem(keyFor(scope), JSON.stringify(list));
  } catch {
    /* not remembered on this device — fine */
  }
}

/**
 * Last searches *per profile* on this device (a kids profile never sees its parent's searches).
 * Device-local on purpose: convenience, not account data.
 */
export function useRecentSearches(scope) {
  const [state, setState] = useState(() => ({ scope, list: read(scope) }));
  const list = state.scope === scope ? state.list : read(scope); // profile switched → that profile's list

  const remember = useCallback(
    (term) => {
      const value = term.trim();
      if (value.length < 2) return;
      const next = [value, ...read(scope).filter((s) => s.toLocaleLowerCase('tr') !== value.toLocaleLowerCase('tr'))].slice(0, MAX);
      write(scope, next);
      setState({ scope, list: next });
    },
    [scope],
  );
  const clear = useCallback(() => {
    write(scope, []);
    setState({ scope, list: [] });
  }, [scope]);

  return { recent: list, remember, clear };
}
