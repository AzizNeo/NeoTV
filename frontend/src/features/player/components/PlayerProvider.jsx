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
import { useChannelEntry } from '../hooks/useChannelEntry';
import { useEndgame } from '../hooks/useEndgame';
import { useMediaSession } from '../hooks/useMediaSession';
import { usePlaybackSession } from '../hooks/usePlaybackSession';
import { useQoe } from '../hooks/useQoe';
import { describeSource } from '../engines';
import { makeQueue, step } from '../queue';
import { DIGITS } from '../shortcuts';
import { useT } from '../i18n';
import { ChannelEntry, NextEpisodeCard, QueueButtons, QueuePanel, UpNext, ZapBadge } from './QueueParts';
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

/** One extra line of "why" for support and curious viewers (never the origin URL). */
function failureHint(fatal, t) {
  if (!fatal) return null;
  if (fatal.reason && ['dns', 'tls', 'timeout', 'connect', 'blocked', 'body'].includes(fatal.reason)) return t(`overlay.reasons.${fatal.reason}`);
  if (fatal.code === 'UPSTREAM_STATUS' && fatal.status) return t('overlay.status', { status: fatal.status });
  return null;
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error('usePlayer() outside <PlayerProvider>');
  return ctx;
}

function PlayerOverlay({ item, queue, onJump, onClose }) {
  const t = useT();
  const { status, session, error } = usePlaybackSession(item.ref);
  const [fatal, setFatal] = useState(null);
  const [video, setVideo] = useState(null);
  const videoRef = useRef(null);
  const engineRef = useRef(null);
  const billing = useFeature('billing');
  const [dismissed, setDismissed] = useState(() => new Set()); // post-play cards the viewer closed
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
  const hasQueue = queue.items.length > 1;
  const channelEntry = useChannelEntry(queue.items.length, onJump);
  // IPTV convention: ↑/↓ (and PgUp/PgDn) change channel, digits type a channel number; volume moves to
  // +/−. On demand, Shift+N / Shift+P move through episodes.
  const extraKeys = useMemo(() => {
    if (!hasQueue) return undefined;
    if (live) {
      return [
        { keys: ['ArrowUp', 'PageUp'], label: t('queue.nextChannel'), run: goNext },
        { keys: ['ArrowDown', 'PageDown'], label: t('queue.prevChannel'), run: goPrev },
        { keys: DIGITS, display: '0–9', label: t('keys.channelNumber'), run: channelEntry.press },
      ];
    }
    return [
      { keys: ['N'], label: t('queue.nextEpisode'), run: goNext },
      { keys: ['P'], label: t('queue.prevEpisode'), run: goPrev },
    ];
  }, [hasQueue, live, goNext, goPrev, channelEntry.press, t]);

  // Post-play (on demand, with a next item): a card during the credits, a countdown at the end.
  const phase = useEndgame(video, { enabled: !live && next !== null, creditsAt: item.creditsAt ?? null });
  const dismiss = (which) => setDismissed((d) => new Set(d).add(which));
  const nextItem = next !== null ? queue.items[next] : null;

  useMediaSession(video, {
    title: item.title ?? session?.content?.title ?? 'NeoTV',
    subtitle: item.subtitle ?? item.caption ?? null,
    artwork: item.image ?? null,
    isLive: live,
    onNext: next !== null ? goNext : null,
    onPrev: prev !== null ? goPrev : null,
  });

  if (problem) {
    return (
      <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={item.title}>
        <div className={styles.card}>
          <AlertTriangle size={44} className={styles.icon} aria-hidden="true" />
          <h2>{item.title}</h2>
          <p>{messageFor(problem, t('overlay.failed'))}</p>
          {failureHint(fatal, t) && <p className={styles.hint}>{failureHint(fatal, t)}</p>}
          <div className={styles.actions}>
            {problem === 'STREAM_LIMIT_EXCEEDED' && billing && (
              <Link to="/plans" className={styles.upgrade} onClick={onClose}>
                {t('overlay.plans')}
              </Link>
            )}
            {next !== null && (
              <button className={styles.secondary} onClick={goNext}>
                <SkipForward size={18} aria-hidden="true" /> {t(live ? 'queue.nextChannel' : 'queue.nextEpisode')}
              </button>
            )}
            <button className={styles.close} onClick={onClose} autoFocus>
              <X size={18} aria-hidden="true" /> {t('close')}
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
        <p className={styles.opening}>{t('overlay.opening', { title: item.title })}</p>
        <button className={styles.close} onClick={onClose}>
          {t('overlay.giveUp')}
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
          engineRef={engineRef}
          extraKeys={extraKeys}
          controlsExtra={
            hasQueue && (
              <QueueButtons live={live} canPrev={prev !== null} canNext={next !== null} onPrev={goPrev} onNext={goNext} onList={() => setListOpen((o) => !o)} />
            )
          }
          overlay={
            <>
              {live && hasQueue && !channelEntry.digits && <ZapBadge number={queue.index + 1} title={item.title} caption={item.caption} />}
              {live && <ChannelEntry digits={channelEntry.digits} invalid={channelEntry.invalid} />}
              {phase === 'credits' && !dismissed.has('credits') && <NextEpisodeCard item={nextItem} onPlay={goNext} onDismiss={() => dismiss('credits')} />}
              {phase === 'ended' && queue.autoNext && !dismissed.has('ended') && <UpNext item={nextItem} onPlay={goNext} onCancel={() => dismiss('ended')} />}
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
