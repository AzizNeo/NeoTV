/**
 * App-wide player: any feature calls `usePlayer().play({ ref, title })`, optionally with a queue —
 * `play(item, { queue: [...] })` — for "next episode" and channel zapping (see ../queue.js).
 * The overlay owns the playback session; other features observe playback via
 * the `player.observers` slot (e.g. library saves resume positions) without
 * the player knowing them.
 */
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, SkipForward, X } from 'lucide-react';
import { Slot, useFeature } from '@/core/featureKit';
import { messageFor } from '@/core/i18n';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { usePlaybackSession } from '../hooks/usePlaybackSession';
import { useQoe } from '../hooks/useQoe';
import { describeSource } from '../engines';
import { makeQueue, step } from '../queue';
import { QueueButtons, QueuePanel, UpNext, ZapBadge } from './QueueParts';
import styles from './PlayerOverlay.module.css';

const CustomPlayer = lazy(() => import('./CustomPlayer').then((m) => ({ default: m.CustomPlayer })));
const PlayerContext = createContext(null);

export function PlayerProvider({ children }) {
  const [state, setState] = useState(null); // { queue, nonce }
  const play = useCallback((item, options = {}) => setState({ queue: makeQueue(item, options.queue, options), nonce: Date.now() }), []);
  const jump = useCallback(
    (index) => setState((s) => (s && index >= 0 && index < s.queue.items.length ? { queue: { ...s.queue, index }, nonce: Date.now() } : s)),
    [],
  );
  const stop = useCallback(() => setState(null), []);
  const current = state ? state.queue.items[state.queue.index] : null;
  const value = useMemo(() => ({ play, stop, current }), [play, stop, current]);
  return (
    <PlayerContext.Provider value={value}>
      {children}
      {/* A new key per item: a fresh playback session per episode/channel (the server swaps the slot). */}
      {current && <PlayerOverlay key={`${current.ref}:${state.nonce}`} item={current} queue={state.queue} onJump={jump} onClose={stop} />}
    </PlayerContext.Provider>
  );
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error('usePlayer() outside <PlayerProvider>');
  return ctx;
}

function PlayerOverlay({ item, queue, onJump, onClose }) {
  const { status, session, error } = usePlaybackSession(item.ref);
  const [fatal, setFatal] = useState(null);
  const [video, setVideo] = useState(null);
  const videoRef = useRef(null);
  const engineRef = useRef(null);
  const billing = useFeature('billing');
  const [ended, setEnded] = useState(false);
  const [listOpen, setListOpen] = useState(false);

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
  const live = Boolean(source?.isLive ?? item.live);
  const prev = step(queue, -1, { wrap: live });
  const next = step(queue, 1, { wrap: live });
  const goNext = useCallback(() => next !== null && onJump(next), [next, onJump]);
  const goPrev = useCallback(() => prev !== null && onJump(prev), [prev, onJump]);
  // IPTV convention: ↑/↓ change channel on live TV (volume stays on +/- and the slider); on demand
  // Shift+N / Shift+P move through episodes.
  const extraKeys = useMemo(
    () => (live ? { ArrowUp: goNext, ArrowDown: goPrev, PageUp: goNext, PageDown: goPrev } : { N: goNext, P: goPrev }),
    [live, goNext, goPrev],
  );

  if (problem) {
    return (
      <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={item.title}>
        <div className={styles.card}>
          <AlertTriangle size={44} className={styles.icon} aria-hidden="true" />
          <h2>{item.title}</h2>
          <p>{messageFor(problem, 'Yayın oynatılamadı.')}</p>
          <div className={styles.actions}>
            {problem === 'STREAM_LIMIT_EXCEEDED' && billing && (
              <Link to="/plans" className={styles.upgrade} onClick={onClose}>
                Planları gör
              </Link>
            )}
            {next !== null && (
              <button className={styles.secondary} onClick={goNext}>
                <SkipForward size={18} aria-hidden="true" /> {live ? 'Sonraki kanal' : 'Sonraki bölüm'}
              </button>
            )}
            <button className={styles.close} onClick={onClose} autoFocus>
              <X size={18} aria-hidden="true" /> Kapat
            </button>
          </div>
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
        <CustomPlayer
          source={source}
          title={item.title ?? session.content?.title}
          subtitle={item.subtitle ?? item.caption}
          onClose={onClose}
          onFatal={setFatal}
          onVideo={onVideo}
          onEnded={() => !live && next !== null && queue.autoNext && setEnded(true)}
          engineRef={engineRef}
          extraKeys={queue.items.length > 1 ? extraKeys : undefined}
          controlsExtra={
            queue.items.length > 1 && (
              <QueueButtons live={live} canPrev={prev !== null} canNext={next !== null} onPrev={goPrev} onNext={goNext} onList={() => setListOpen((o) => !o)} />
            )
          }
          overlay={
            <>
              {live && queue.items.length > 1 && <ZapBadge number={queue.index + 1} title={item.title} caption={item.caption} />}
              {ended && next !== null && <UpNext item={queue.items[next]} onPlay={goNext} onCancel={() => setEnded(false)} />}
              {listOpen && <QueuePanel live={live} items={queue.items} index={queue.index} onPick={onJump} onClose={() => setListOpen(false)} />}
            </>
          }
        >
          {video && <Slot name="player.observers" video={video} contentRef={item.ref} isLive={source.isLive} sessionToken={session.session_token} />}
        </CustomPlayer>
      </Suspense>
    </div>
  );
}
