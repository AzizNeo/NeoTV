/**
 * Full-screen player UI (look & feel of the v1 player), rebuilt on the engine
 * abstraction with deterministic cleanup (FE-07):
 *   * the engine is created once per manifest URL and destroyed on change/unmount;
 *   * every DOM listener is removed; no handler captures stale state;
 *   * resume position is applied by an observer, never by re-creating the engine.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Captions, CaptionsOff, PictureInPicture2 } from 'lucide-react';
import { createEngine } from '../engines';
import { NO_TRACKS, OFF, sameLanguage } from '../engines/tracks';
import { applyPreferences, readPrefs, writePrefs } from '../prefs';
import { DIGITS, ignoreKey, resolveShortcuts } from '../shortcuts';
import { useT } from '../i18n';
import { SettingsMenu, ShortcutHelp } from './PlayerMenus';
import './CustomPlayer.css';

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return '0:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, '0') : String(m);
  return `${h ? `${h}:` : ''}${mm}:${String(s).padStart(2, '0')}`;
}

const STARTUP_TIMEOUT_MS = 25_000;
const canPip = () => typeof document !== 'undefined' && Boolean(document.pictureInPictureEnabled);

/**
 * Extension points (all optional) keep this component generic — it knows nothing of episodes or channels:
 * `subtitle` (title bar), `controlsExtra` (buttons before settings), `overlay` (layers over the video),
 * `extraKeys` (shortcuts `{ keys, label, run }` that win over the defaults — live TV maps ↑/↓ to
 * channels — and show up in the "?" help), `onEnded`.
 */
export function CustomPlayer({ source, title, subtitle, onClose, onFatal, onVideo, onEnded, engineRef, extraKeys, controlsExtra, overlay, children }) {
  const t = useT();
  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const progressRef = useRef(null);
  const hideTimer = useRef(null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [showVolume, setShowVolume] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [tracks, setTracks] = useState(NO_TRACKS);
  const [showHelp, setShowHelp] = useState(false);
  const [isPip, setIsPip] = useState(false);
  const engineHandle = useRef(null); // the live engine, for menu actions
  const lastText = useRef(null); // the subtitle language "C" turns back on

  const isLive = source.isLive;
  const onFatalRef = useRef(onFatal);
  onFatalRef.current = onFatal;
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;

  // ── engine lifecycle ────────────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    let engine = null;
    let disposed = false;
    const applied = { text: false, audio: false }; // remembered languages: applied once per source
    const prefs = readPrefs();
    setIsLoading(true);
    setTracks(NO_TRACKS);
    // Watchdog: whatever goes wrong upstream, a viewer never stares at an endless spinner.
    const watchdog = setTimeout(() => {
      if (!disposed) onFatalRef.current?.({ code: 'STREAM_TIMEOUT' });
    }, STARTUP_TIMEOUT_MS);
    // Created on the next tick: a mount that is torn down at once (StrictMode) builds no engine at all.
    const start = setTimeout(() =>
    createEngine(video, source, {
      onReady: () => {
        clearTimeout(watchdog);
        setIsLoading(false);
        video.play().catch(() => {
          /* autoplay blocked: user presses play */
        });
      },
      onFatal: (failure) => onFatalRef.current?.(failure),
      onTracks: () => {
        if (disposed || !engine) return;
        applyPreferences(engine, engine.tracks(), prefs, applied);
        setTracks(engine.tracks());
      },
    })
      .then((created) => {
        if (disposed) {
          created.destroy();
          return;
        }
        engine = created;
        engineHandle.current = created;
        if (engineRef) engineRef.current = created;
        return created.load(source.url);
      })
      .catch((error) => onFatalRef.current?.({ code: error.code ?? 'UNSUPPORTED_PLAYBACK', detail: error.message })), 0);
    return () => {
      disposed = true;
      clearTimeout(start);
      clearTimeout(watchdog);
      engine?.destroy();
      engineHandle.current = null;
      if (engineRef) engineRef.current = null;
    };
    // The engine depends on the manifest only — never on UI state (FE-07).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.url]);

  useEffect(() => {
    onVideo?.(videoRef.current);
    return () => onVideo?.(null);
  }, [onVideo]);

  // ── media element → UI state ─────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current;
    const saved = readPrefs();
    if (Number.isFinite(saved.volume)) video.volume = Math.max(0, Math.min(1, saved.volume));
    if (typeof saved.muted === 'boolean') video.muted = saved.muted;
    setVolume(video.volume);
    setIsMuted(video.muted);
    const handlers = {
      play: () => setIsPlaying(true),
      pause: () => setIsPlaying(false),
      timeupdate: () => {
        setCurrentTime(video.currentTime);
        if (video.buffered.length) setBuffered(video.buffered.end(video.buffered.length - 1));
      },
      durationchange: () => setDuration(video.duration),
      volumechange: () => {
        setVolume(video.volume);
        setIsMuted(video.muted);
        writePrefs({ volume: video.volume, muted: video.muted });
      },
      enterpictureinpicture: () => setIsPip(true),
      leavepictureinpicture: () => setIsPip(false),
      waiting: () => setIsLoading(true),
      playing: () => setIsLoading(false),
      ended: () => {
        setIsPlaying(false);
        onEndedRef.current?.();
      },
    };
    for (const [event, fn] of Object.entries(handlers)) video.addEventListener(event, fn);
    // Subtitles sit on the bottom line by default — under the control bar. Lift cues that carry no
    // position of their own four lines up (standard VTTCue API: works with every engine and browser).
    // "No position" is 'auto', or -1 (the bottom line), which hls.js writes in its place for Safari.
    // Every cue of the track is moved up front; one already on screen is re-added, because a
    // browser does not re-lay out a cue that changes while it is displayed.
    const unplaced = (cue) => cue.line === 'auto' || cue.line === -1;
    const lift = (event) => {
      const track = event.target;
      const showing = new Set(track.activeCues ?? []);
      for (const cue of [...(track.cues ?? [])].filter(unplaced)) {
        cue.line = -4;
        if (showing.has(cue)) {
          track.removeCue(cue);
          track.addCue(cue);
        }
      }
    };
    const watch = (event) => event.track.addEventListener('cuechange', lift);
    for (const track of video.textTracks ?? []) track.addEventListener('cuechange', lift);
    video.textTracks?.addEventListener('addtrack', watch);
    return () => {
      for (const [event, fn] of Object.entries(handlers)) video.removeEventListener(event, fn);
      video.textTracks?.removeEventListener('addtrack', watch);
      for (const track of video.textTracks ?? []) track.removeEventListener('cuechange', lift);
      if (document.pictureInPictureElement === video) document.exitPictureInPicture().catch(() => {});
    };
  }, []);

  useEffect(() => {
    const onChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  // ── controls ─────────────────────────────────────────────────────────────
  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  }, []);

  const skip = useCallback(
    (seconds) => {
      const video = videoRef.current;
      if (isLive || !Number.isFinite(video.duration)) return;
      video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
    },
    [isLive],
  );

  const changeVolume = useCallback((delta) => {
    const video = videoRef.current;
    video.volume = Math.max(0, Math.min(1, video.volume + delta));
    if (video.volume > 0) video.muted = false;
  }, []);

  const toggleMute = useCallback(() => {
    videoRef.current.muted = !videoRef.current.muted;
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) playerRef.current?.requestFullscreen?.().catch(() => {});
    else document.exitFullscreen().catch(() => {});
  }, []);

  const togglePip = useCallback(() => {
    if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
    else videoRef.current?.requestPictureInPicture?.().catch(() => {});
  }, []);

  const seekFraction = useCallback(
    (fraction) => {
      const video = videoRef.current;
      if (!isLive && Number.isFinite(video.duration)) video.currentTime = video.duration * fraction;
    },
    [isLive],
  );

  /** Menu choice → engine; languages are remembered for the next episode / visit. */
  const selectTrack = useCallback((kind, id) => {
    const engine = engineHandle.current;
    if (!engine) return;
    engine.select(kind, id);
    const chosen = engine.tracks()[kind].find((t) => t.id === id);
    if (kind === 'text') {
      if (chosen?.lang) lastText.current = chosen.lang;
      writePrefs({ textLang: id === OFF ? 'off' : (chosen?.lang ?? null) });
    } else if (kind === 'audio' && chosen?.lang) {
      writePrefs({ audioLang: chosen.lang });
    }
  }, []);

  const toggleSubtitles = useCallback(() => {
    const engine = engineHandle.current;
    if (!engine) return;
    const { text, textId } = engine.tracks();
    if (!text.length) return;
    if (textId !== OFF) {
      selectTrack('text', OFF);
      return;
    }
    const wanted = lastText.current ?? (readPrefs().textLang !== 'off' ? readPrefs().textLang : null);
    selectTrack('text', (text.find((t) => sameLanguage(t.lang, wanted)) ?? text[0]).id);
  }, [selectTrack]);

  // While a menu or the help is open the controls stay put (keyboard users are mid-way through it).
  const pinned = useRef(false);
  pinned.current = showSettings || showHelp;
  const revealControls = useCallback(() => {
    setShowControls(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      if (!videoRef.current?.paused && !pinned.current) {
        setShowControls(false);
        setShowSettings(false);
      }
    }, 3000);
  }, []);

  useEffect(() => () => clearTimeout(hideTimer.current), []);

  // Keyboard: one shortcut list drives the handler *and* the "?" help (see ../shortcuts.js).
  const hasText = tracks.text.length > 0;
  const pipAvailable = canPip();
  const shortcuts = resolveShortcuts(
    [
      { keys: [' ', 'k'], label: t('keys.playPause'), run: togglePlay },
      !isLive && { keys: ['ArrowLeft', 'j'], label: t('back10'), run: () => skip(-10) },
      !isLive && { keys: ['ArrowRight', 'l'], label: t('forward10'), run: () => skip(10) },
      !isLive && { keys: DIGITS, display: '0–9', label: t('keys.seekPercent'), run: (key) => seekFraction(Number(key) / 10) },
      { keys: ['ArrowUp', '+', '='], label: t('keys.volumeUp'), run: () => changeVolume(0.1) },
      { keys: ['ArrowDown', '-'], label: t('keys.volumeDown'), run: () => changeVolume(-0.1) },
      { keys: ['m'], label: t('keys.muteToggle'), run: toggleMute },
      hasText && { keys: ['c'], label: t('keys.subtitles'), run: toggleSubtitles },
      { keys: ['f'], label: t('fullscreen'), run: toggleFullscreen },
      pipAvailable && { keys: ['i'], label: t('pip'), run: togglePip },
      { keys: ['?'], label: t('keys.help'), run: () => setShowHelp((v) => !v) },
      {
        keys: ['Escape'],
        label: t('keys.escape'),
        run: () => {
          if (showHelp) setShowHelp(false);
          else if (showSettings) setShowSettings(false);
          else if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
          else onClose?.();
        },
      },
    ].filter(Boolean),
    extraKeys,
    { space: t('keys.space'), locale: t.locale },
  );
  const shortcutsRef = useRef(shortcuts);
  shortcutsRef.current = shortcuts;
  useEffect(() => {
    const onKey = (event) => {
      if (ignoreKey(event)) return;
      const shortcut = shortcutsRef.current.byKey.get(event.key);
      if (!shortcut) return;
      event.preventDefault();
      shortcut.run(event.key);
      revealControls();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [revealControls]);

  const seekTo = (event) => {
    if (isLive || !duration) return;
    const rect = progressRef.current.getBoundingClientRect();
    videoRef.current.currentTime = ((event.clientX - rect.left) / rect.width) * duration;
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
  const bufferedPct = duration > 0 ? (buffered / duration) * 100 : 0;

  return (
    <div
      ref={playerRef}
      className={`custom-player ${showControls ? '' : 'hide-cursor'}`}
      onMouseMove={revealControls}
      onClick={(e) => {
        if (e.target !== playerRef.current && e.target !== videoRef.current) return;
        if (showSettings) setShowSettings(false); // a click outside the menu just closes it (YouTube)
        else togglePlay();
      }}
      role="region"
      aria-label={t('region', { title })}
    >
      <video ref={videoRef} className="video-element" playsInline />

      {isLoading && (
        <div className="loading-overlay" aria-hidden="true">
          <div className="spinner" />
        </div>
      )}

      {isPip && (
        <div className="pip-placeholder">
          <PictureInPicture2 size={40} aria-hidden="true" />
          <span>{t('pipActive')}</span>
          <button type="button" onClick={togglePip}>
            {t('pipBack')}
          </button>
        </div>
      )}

      {children}
      {overlay}
      {showHelp && <ShortcutHelp shortcuts={shortcuts.list} onClose={() => setShowHelp(false)} />}

      <div className={`title-bar ${showControls ? 'visible' : ''}`}>
        <button className="back-btn" onClick={onClose} aria-label={t('close')}>
          <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" /></svg>
        </button>
        <span className="title">{title}</span>
        {subtitle && <span className="subtitle">{subtitle}</span>}
        {isLive && <span className="live-badge">{t('live')}</span>}
      </div>

      <div className={`controls ${showControls ? 'visible' : ''}`}>
        {!isLive && (
          <div
            className="progress-container"
            ref={progressRef}
            onClick={seekTo}
            role="slider"
            aria-label={t('progress')}
            aria-valuemin={0}
            aria-valuemax={Math.round(duration) || 0}
            aria-valuenow={Math.round(currentTime)}
            tabIndex={0}
          >
            <div className="progress-buffered" style={{ width: `${bufferedPct}%` }} />
            <div className="progress-played" style={{ width: `${progress}%` }} />
            <div className="progress-handle" style={{ left: `${progress}%` }} />
          </div>
        )}

        <div className="controls-row">
          <div className="controls-left">
            <button className="control-btn" onClick={togglePlay} aria-label={t(isPlaying ? 'pause' : 'play')}>
              {isPlaying ? (
                <svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg>
              ) : (
                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
              )}
            </button>
            {!isLive && (
              <>
                <button className="control-btn" onClick={() => skip(-10)} aria-label={t('back10')}>
                  <svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z" /></svg>
                  <span className="skip-text">10</span>
                </button>
                <button className="control-btn" onClick={() => skip(10)} aria-label={t('forward10')}>
                  <svg viewBox="0 0 24 24"><path d="M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z" /></svg>
                  <span className="skip-text">10</span>
                </button>
              </>
            )}
            <div className="volume-control" onMouseEnter={() => setShowVolume(true)} onMouseLeave={() => setShowVolume(false)}>
              <button className="control-btn" onClick={toggleMute} aria-label={t(isMuted ? 'unmute' : 'mute')}>
                {isMuted || volume === 0 ? (
                  <svg viewBox="0 0 24 24"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z" /></svg>
                ) : (
                  <svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" /></svg>
                )}
              </button>
              <div className={`volume-slider-container ${showVolume ? 'visible' : ''}`}>
                <input
                  type="range"
                  className="volume-slider"
                  min="0"
                  max="1"
                  step="0.05"
                  aria-label={t('volume')}
                  value={isMuted ? 0 : volume}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    videoRef.current.volume = v;
                    if (v > 0) videoRef.current.muted = false;
                  }}
                />
              </div>
            </div>
            {!isLive && (
              <span className="time-display">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            )}
          </div>

          <div className="controls-right">
            {controlsExtra}
            {hasText && (
              <button
                className="control-btn"
                onClick={toggleSubtitles}
                aria-label={t(tracks.textId === OFF ? 'subtitlesOn' : 'subtitlesOff')}
                aria-pressed={tracks.textId !== OFF}
              >
                {tracks.textId === OFF ? <CaptionsOff size={24} aria-hidden="true" /> : <Captions size={24} aria-hidden="true" />}
              </button>
            )}
            {pipAvailable && (
              <button className="control-btn" onClick={togglePip} aria-label={t(isPip ? 'pipExit' : 'pip')} aria-pressed={isPip}>
                <PictureInPicture2 size={24} aria-hidden="true" />
              </button>
            )}
            <div className="settings-container">
              <button className="control-btn" onClick={() => setShowSettings((v) => !v)} aria-label={t('settings')} aria-haspopup="menu" aria-expanded={showSettings}>
                <svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" /></svg>
              </button>
              {showSettings && (
                <SettingsMenu
                  tracks={tracks}
                  speed={speed}
                  speeds={SPEEDS}
                  isLive={isLive}
                  onSelect={selectTrack}
                  onSpeed={(s) => {
                    videoRef.current.playbackRate = s;
                    setSpeed(s);
                  }}
                  onHelp={() => {
                    setShowSettings(false);
                    setShowHelp(true);
                  }}
                  onClose={() => setShowSettings(false)}
                />
              )}
            </div>
            <button className="control-btn" onClick={toggleFullscreen} aria-label={t(isFullscreen ? 'fullscreenExit' : 'fullscreen')}>
              {isFullscreen ? (
                <svg viewBox="0 0 24 24"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z" /></svg>
              ) : (
                <svg viewBox="0 0 24 24"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z" /></svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

CustomPlayer.propTypes = {
  source: PropTypes.shape({
    url: PropTypes.string.isRequired,
    isLive: PropTypes.bool,
    isHls: PropTypes.bool,
    drm: PropTypes.object,
    maxHeight: PropTypes.number,
  }).isRequired,
  title: PropTypes.string.isRequired,
  onClose: PropTypes.func.isRequired,
  subtitle: PropTypes.string,
  onEnded: PropTypes.func,
  extraKeys: PropTypes.arrayOf(
    PropTypes.shape({ keys: PropTypes.arrayOf(PropTypes.string).isRequired, label: PropTypes.string.isRequired, run: PropTypes.func.isRequired, display: PropTypes.string }),
  ),
  controlsExtra: PropTypes.node,
  overlay: PropTypes.node,
  onFatal: PropTypes.func,
  onVideo: PropTypes.func,
  engineRef: PropTypes.object,
  children: PropTypes.node,
};
