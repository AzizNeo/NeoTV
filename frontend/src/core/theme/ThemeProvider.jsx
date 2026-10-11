import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

/**
 * Theme: 'system' (default) follows the OS and keeps following it; 'dark' / 'light' pin it.
 * `public/theme-boot.js` applies the saved choice before first paint; this provider owns it afterwards.
 */
const STORAGE_KEY = 'neotv.theme';
const CHOICES = ['system', 'dark', 'light'];
const query = () => window.matchMedia('(prefers-color-scheme: light)');

const ThemeContext = createContext(null);

function readChoice() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return CHOICES.includes(saved) ? saved : 'system';
  } catch {
    return 'system'; // storage blocked (private mode, policies): still works, just not remembered
  }
}

const resolve = (choice, systemLight) => (choice === 'system' ? (systemLight ? 'light' : 'dark') : choice);

export function ThemeProvider({ children }) {
  const [choice, setChoice] = useState(readChoice);
  const [systemLight, setSystemLight] = useState(() => query().matches);

  useEffect(() => {
    const media = query();
    const onChange = (e) => setSystemLight(e.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const resolved = resolve(choice, systemLight);
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'light' ? '#f3f5f9' : '#121826');
  }, [resolved]);

  const setTheme = useCallback((next) => {
    if (!CHOICES.includes(next)) throw new Error(`unknown theme '${next}'`);
    setChoice(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* not remembered — still applied for this visit */
    }
  }, []);

  const value = useMemo(() => ({ theme: choice, resolved, setTheme, choices: CHOICES }), [choice, resolved, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme() outside <ThemeProvider>');
  return ctx;
}
