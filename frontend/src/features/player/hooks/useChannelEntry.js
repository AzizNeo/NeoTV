import { useCallback, useEffect, useRef, useState } from 'react';

const COMMIT_MS = 1500;

/**
 * Remote-control channel numbers (IPTV): type 1 then 2 → channel 12. The number commits after a
 * short pause, or at once when no longer number is possible (12 of 40 channels waits; 5 of 9 doesn't).
 * Returns { digits, invalid, press(key) }; `digits` is what the on-screen badge shows.
 */
export function useChannelEntry(count, onPick) {
  const [digits, setDigits] = useState('');
  const [invalid, setInvalid] = useState(false);
  const typed = useRef(''); // the source of truth; state only drives the badge
  const timer = useRef(null);
  const maxLength = String(count).length;

  const show = useCallback((value) => {
    typed.current = value;
    setDigits(value);
  }, []);

  const commit = useCallback(
    (value) => {
      clearTimeout(timer.current);
      const n = Number(value);
      if (n >= 1 && n <= count) {
        show('');
        onPick(n - 1);
        return;
      }
      setInvalid(true);
      timer.current = setTimeout(() => {
        show('');
        setInvalid(false);
      }, COMMIT_MS);
    },
    [count, onPick, show],
  );

  const press = useCallback(
    (key) => {
      clearTimeout(timer.current);
      setInvalid(false);
      const value = (typed.current + key).replace(/^0+/, '').slice(-maxLength);
      show(value);
      if (!value) return;
      // Nothing longer can still be valid → no reason to make the viewer wait.
      if (value.length === maxLength || Number(value) * 10 > count) commit(value);
      else timer.current = setTimeout(() => commit(value), COMMIT_MS);
    },
    [commit, count, maxLength, show],
  );

  useEffect(() => () => clearTimeout(timer.current), []);
  return { digits, invalid, press };
}
