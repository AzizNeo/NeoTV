import { createContext, useContext } from 'react';

/**
 * The few words shared components say themselves ("Canlı", "Kapat"…). `shared/` must not depend
 * on the i18n core, so the composition root (app/) provides them already translated — dependency
 * inversion: the shared layer declares *what* it needs, the app decides the language.
 */
const DEFAULT_TEXT = Object.freeze({
  live: 'Canlı',
  close: 'Kapat',
  playItem: (title) => `${title} oynat`,
});

const SharedTextContext = createContext(DEFAULT_TEXT);

export function SharedTextProvider({ value, children }) {
  return <SharedTextContext.Provider value={{ ...DEFAULT_TEXT, ...value }}>{children}</SharedTextContext.Provider>;
}

export const useSharedText = () => useContext(SharedTextContext);
