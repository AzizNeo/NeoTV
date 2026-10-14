import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import styles from './Toast.module.css';
import { useSharedText } from '../SharedText/SharedTextProvider';

const ToastContext = createContext(null);
let nextId = 1;

/** Non-blocking notifications (replaces window.alert / window.confirm flows). */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (tone, text, ttl = 4500) => {
      const id = nextId++;
      setToasts((list) => [...list.slice(-3), { id, tone, text }]);
      timers.current.set(id, setTimeout(() => dismiss(id), ttl));
      return id;
    },
    [dismiss],
  );

  const api = useMemo(
    () => ({
      success: (text) => push('success', text),
      error: (text) => push('error', text, 7000),
      info: (text) => push('info', text),
      dismiss,
    }),
    [push, dismiss],
  );

  const text = useSharedText();
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.stack} aria-live="polite" aria-atomic="false">
        {toasts.map((t) => (
          <div key={t.id} className={`${styles.toast} ${styles[t.tone]}`} role={t.tone === 'error' ? 'alert' : 'status'}>
            <span>{t.text}</span>
            <button className={styles.close} onClick={() => dismiss(t.id)} aria-label={text.close}>
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast() outside <ToastProvider>');
  return ctx;
}
