/**
 * Full-screen player UI (look & feel of the v1 player), rebuilt on the engine
 * abstraction with deterministic cleanup (FE-07):
 *   * the engine is created once per manifest URL and destroyed on change/unmount;
 *   * every DOM listener is removed; no handler captures stale state;
 *   * resume position is applied by an observer, never by re-creating the engine.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { createEngine } from '../engines';
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

/**
 * Extension points (all optional) keep this component generic — it knows nothing of episodes or channels:
 * `subtitle` (title bar), `controlsExtra` (buttons before settings), `overlay` (layers over the video),
 * `extraKeys` (key → action, overrides defaults: live TV maps ↑/↓ to channels), `onEnded`.
 */
export function CustomPlayer({ source, title, subtitle, onClose, onFatal, onVideo, onEnded, engineRef, extraKeys, controlsExtra, overlay, children }) {
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
    setIsLoading(true);
    createEngine(video, source, {
      onReady: () => {
        setIsLoading(false);
        video.play().catch(() => {
          /* autoplay blocked: user presses play */
        });
      },
      onFatal: (failure) => onFatalRef.current?.(failure),
    })
      .then((created) => {
        if (disposed) {
          created.destroy();
          return;
        }
        engine = created;
        if (engineRef) engineRef.current = created;
        return created.load(source.url);
      })
      .catch((error) => onFatalRef.current?.({ code: error.code ?? 'UNSUPPORTED_PLAYBACK', detail: error.message }));
    return () => {
      disposed = true;
      engine?.destroy();
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
      },
      waiting: () => setIsLoading(true),
      playing: () => setIsLoading(false),
      ended: () => {
        setIsPlaying(false);
        onEndedRef.current?.();
      },
    };
    for (const [event, fn] of Object.entries(handlers)) video.addEventListener(event, fn);
    return () => {
      for (const [event, fn] of Object.entries(handlers)) video.removeEventListener(event, fn);
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

  const revealControls = useCallback(() => {
    setShowControls(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      if (!videoRef.current?.paused) {
        setShowControls(false);
        setShowSettings(false);
      }
    }, 3000);
  }, []);

  useEffect(() => () => clearTimeout(hideTimer.current), []);

  // Keyboard: handlers read the latest callbacks through a ref (no stale closures).
  const keyActions = useRef({});
  keyActions.current = { togglePlay, skip, changeVolume, toggleFullscreen, toggleMute, onClose, extraKeys };
  useEffect(() => {
    const onKey = (event) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
      const a = keyActions.current;
      const map = {
        ' ': a.togglePlay,
        k: a.togglePlay,
        ArrowLeft: () => a.skip(-10),
        ArrowRight: () => a.skip(10),
        ArrowUp: () => a.changeVolume(0.1),
        ArrowDown: () => a.changeVolume(-0.1),
        f: a.toggleFullscreen,
        m: a.toggleMute,
        Escape: () => (document.fullscreenElement ? document.exitFullscreen() : a.onClose?.()),
        ...a.extraKeys,
      };
      const action = map[event.key];
      if (action) {
        event.preventDefault();
        action();
        revealControls();
      }
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
        if (e.target === playerRef.current || e.target === videoRef.current) togglePlay();
      }}
      role="region"
      aria-label={`${title} oynatıcı`}
    >
      <video ref={videoRef} className="video-element" playsInline />

      {isLoading && (
        <div className="loading-overlay" aria-hidden="true">
          <div className="spinner" />
        </div>
      )}

      {children}
      {overlay}

      <div className={`title-bar ${showControls ? 'visible' : ''}`}>
        <button className="back-btn" onClick={onClose} aria-label="Kapat">
          <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" /></svg>
        </button>
        <span className="title">{title}</span>
        {subtitle && <span className="subtitle">{subtitle}</span>}
        {isLive && <span className="live-badge">CANLI</span>}
      </div>

      <div className={`controls ${showControls ? 'visible' : ''}`}>
        {!isLive && (
          <div
            className="progress-container"
            ref={progressRef}
            onClick={seekTo}
            role="slider"
            aria-label="İlerleme"
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
            <button className="control-btn" onClick={togglePlay} aria-label={isPlaying ? 'Duraklat' : 'Oynat'}>
              {isPlaying ? (
                <svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg>
              ) : (
                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
              )}
            </button>
            {!isLive && (
              <>
                <button className="control-btn" onClick={() => skip(-10)} aria-label="10 saniye geri">
                  <svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z" /></svg>
                  <span className="skip-text">10</span>
                </button>
                <button className="control-btn" onClick={() => skip(10)} aria-label="10 saniye ileri">
                  <svg viewBox="0 0 24 24"><path d="M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z" /></svg>
                  <span className="skip-text">10</span>
                </button>
              </>
            )}
            <div className="volume-control" onMouseEnter={() => setShowVolume(true)} onMouseLeave={() => setShowVolume(false)}>
              <button className="control-btn" onClick={toggleMute} aria-label={isMuted ? 'Sesi aç' : 'Sesi kapat'}>
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
                  aria-label="Ses düzeyi"
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
            {!isLive && (
              <div className="settings-container">
                <button className="control-btn" onClick={() => setShowSettings((v) => !v)} aria-label="Ayarlar" aria-expanded={showSettings}>
                  <svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" /></svg>
                </button>
                {showSettings && (
                  <div className="settings-menu">
                    <div className="settings-section">
                      <div className="settings-title">Oynatma hızı</div>
                      {SPEEDS.map((s) => (
                        <button
                          key={s}
                          className={`settings-option ${speed === s ? 'active' : ''}`}
                          onClick={() => {
                            videoRef.current.playbackRate = s;
                            setSpeed(s);
                            setShowSettings(false);
                          }}
                        >
                          {s === 1 ? 'Normal' : `${s}x`}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            <button className="control-btn" onClick={toggleFullscreen} aria-label={isFullscreen ? 'Tam ekrandan çık' : 'Tam ekran'}>
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
  extraKeys: PropTypes.objectOf(PropTypes.func),
  controlsExtra: PropTypes.node,
  overlay: PropTypes.node,
  onFatal: PropTypes.func,
  onVideo: PropTypes.func,
  engineRef: PropTypes.object,
  children: PropTypes.node,
};
