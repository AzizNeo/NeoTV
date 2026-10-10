/**
 * App-wide player: any feature calls `usePlayer().play({ ref, title })`.
 * The overlay owns the playback session; other features observe playback via
 * the `player.observers` slot (e.g. library saves resume positions) without
 * the player knowing them.
 */
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, X } from 'lucide-react';
import { Slot, useFeature } from '@/core/featureKit';
import { messageFor } from '@/core/i18n';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { usePlaybackSession } from '../hooks/usePlaybackSession';
import { useQoe } from '../hooks/useQoe';
import { describeSource } from '../engines';
import styles from './PlayerOverlay.module.css';

const CustomPlayer = lazy(() => import('./CustomPlayer').then((m) => ({ default: m.CustomPlayer })));
const PlayerContext = createContext(null);

export function PlayerProvider({ children }) {
  const [current, setCurrent] = useState(null);
  const play = useCallback((item) => setCurrent({ ref: item.ref, title: item.title, nonce: Date.now() }), []);
  const stop = useCallback(() => setCurrent(null), []);
  const value = useMemo(() => ({ play, stop, current }), [play, stop, current]);
  return (
    <PlayerContext.Provider value={value}>
      {children}
      {current && <PlayerOverlay key={`${current.ref}:${current.nonce}`} item={current} onClose={stop} />}
    </PlayerContext.Provider>
  );
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error('usePlayer() outside <PlayerProvider>');
  return ctx;
}

function PlayerOverlay({ item, onClose }) {
  const { status, session, error } = usePlaybackSession(item.ref);
  const [fatal, setFatal] = useState(null);
  const [video, setVideo] = useState(null);
  const videoRef = useRef(null);
  const engineRef = useRef(null);
  const billing = useFeature('billing');

  const onVideo = useCallback((el) => {
    videoRef.current = el;
    setVideo(el);
  }, []);
  useQoe(videoRef, { contentRef: item.ref, sessionToken: session?.session_token, engineRef });

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  const source = useMemo(() => (session ? describeSource(session) : null), [session]);
  const problem = status === 'denied' || status === 'expired' ? error?.code : fatal?.code;

  if (problem) {
    return (
      <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={item.title}>
        <div className={styles.card}>
          <AlertTriangle size={44} className={styles.icon} aria-hidden="true" />
          <h2>{item.title}</h2>
          <p>{messageFor(problem, 'Yayın oynatılamadı.')}</p>
          {problem === 'STREAM_LIMIT_EXCEEDED' && billing && (
            <Link to="/plans" className={styles.upgrade} onClick={onClose}>
              Planları gör
            </Link>
          )}
          <button className={styles.close} onClick={onClose} autoFocus>
            <X size={18} aria-hidden="true" /> Kapat
          </button>
        </div>
      </div>
    );
  }

  if (status !== 'ready' || !source) {
    return (
      <div className={styles.overlay} role="dialog" aria-modal="true" aria-busy="true" aria-label={item.title}>
        <Spinner size="lg" />
        <p className={styles.opening}>{item.title} açılıyor…</p>
        <button className={styles.close} onClick={onClose}>
          Vazgeç
        </button>
      </div>
    );
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={item.title}>
      <Suspense fallback={<Spinner size="lg" />}>
        <CustomPlayer source={source} title={session.content?.title ?? item.title} onClose={onClose} onFatal={setFatal} onVideo={onVideo} engineRef={engineRef}>
          {video && <Slot name="player.observers" video={video} contentRef={item.ref} isLive={source.isLive} sessionToken={session.session_token} />}
        </CustomPlayer>
      </Suspense>
    </div>
  );
}
