/**
 * Player pop-ups: the settings menu (quality · audio · subtitles · speed) and the "?" shortcut list.
 * Pure presentation — choices go back through callbacks; CustomPlayer talks to the engine.
 */
import { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Check, ChevronLeft, ChevronRight, Keyboard, X } from 'lucide-react';
import { AUTO, OFF, qualityLabel, trackLabels } from '../engines/tracks';
import { useT } from '../i18n';
import styles from './PlayerMenus.module.css';


/** Rows of the main view, each with its current value; a row appears only when there is a choice. */
function menuModel(tracks, { speed, speeds, isLive }, t) {
  const naming = { locale: t.locale, unnamed: (n) => t('menu.track', { n }) };
  const audioNames = trackLabels(tracks.audio, naming);
  const textNames = trackLabels(tracks.text, naming);
  const speedLabel = (s) => (s === 1 ? t('menu.normal') : `${s}x`);
  const off = t('menu.off');
  const selected = tracks.quality.find((q) => q.id === tracks.qualityId);
  const autoName = `${t('menu.auto')}${tracks.playingHeight ? ` (${tracks.playingHeight}p)` : ''}`;
  const views = {};
  if (tracks.quality.length > 1) {
    views.quality = {
      title: t('menu.quality'),
      value: selected ? qualityLabel(selected.height) : autoName,
      options: [{ id: AUTO, label: autoName }, ...tracks.quality.map((q) => ({ id: q.id, label: qualityLabel(q.height) }))],
      current: selected ? selected.id : AUTO,
    };
  }
  if (tracks.audio.length > 1) {
    const i = tracks.audio.findIndex((t) => t.id === tracks.audioId);
    views.audio = { title: t('menu.audio'), value: audioNames[i] ?? '', options: tracks.audio.map((t, j) => ({ id: t.id, label: audioNames[j] })), current: tracks.audioId };
  }
  if (tracks.text.length) {
    const i = tracks.text.findIndex((t) => t.id === tracks.textId);
    views.text = {
      title: t('menu.subtitles'),
      value: i === -1 ? off : textNames[i],
      options: [{ id: OFF, label: off }, ...tracks.text.map((t, j) => ({ id: t.id, label: textNames[j] }))],
      current: i === -1 ? OFF : tracks.textId,
    };
  }
  if (!isLive) views.speed = { title: t('menu.speed'), value: speedLabel(speed), options: speeds.map((s) => ({ id: s, label: speedLabel(s) })), current: speed };
  return views;
}

/** Arrow keys move between items; Esc steps back (sub-view → main → closed). Keys never reach the player. */
function menuKeyHandler(onBack) {
  return (event) => {
    const items = [...event.currentTarget.querySelectorAll('button:not(:disabled)')];
    const at = items.indexOf(document.activeElement);
    const moves = { ArrowDown: 1, ArrowUp: -1, Home: -Infinity, End: Infinity };
    if (event.key in moves) {
      const move = moves[event.key];
      const next = Number.isFinite(move) ? (at + move + items.length) % items.length : move < 0 ? 0 : items.length - 1;
      items[next]?.focus();
    } else if (event.key === 'Escape' || event.key === 'ArrowLeft') {
      onBack();
    } else if (event.key !== ' ' && event.key !== 'Enter' && event.key !== 'Tab') {
      return; // other keys (f, m …) still control the player
    }
    if (event.key !== 'Tab') event.preventDefault();
    event.stopPropagation();
  };
}

export function SettingsMenu({ tracks, speed, speeds, isLive, onSelect, onSpeed, onHelp, onClose }) {
  const t = useT();
  const [view, setView] = useState(null);
  const ref = useRef(null);
  const views = menuModel(tracks, { speed, speeds, isLive }, t);
  const open = view && views[view];
  const onKeyDown = menuKeyHandler(() => (open ? setView(null) : onClose()));

  // Focus follows the view: the checked option in a list, the first row on the main view.
  useEffect(() => {
    (ref.current?.querySelector('[aria-checked="true"]') ?? ref.current?.querySelector('button'))?.focus();
  }, [view]);

  return (
    <div ref={ref} className={styles.menu} role="menu" aria-label={open ? open.title : t('settings')} onKeyDown={onKeyDown}>
      {open ? (
        <>
          <button type="button" className={styles.back} onClick={() => setView(null)}>
            <ChevronLeft size={18} aria-hidden="true" /> {open.title}
          </button>
          {open.options.map((o) => (
            <button
              key={o.id}
              type="button"
              role="menuitemradio"
              aria-checked={o.id === open.current}
              className={styles.option}
              onClick={() => {
                if (view === 'speed') onSpeed(o.id);
                else onSelect(view, o.id);
                onClose(); // a choice is made: get out of the way of the picture
              }}
            >
              <span className={styles.check}>{o.id === open.current && <Check size={16} aria-hidden="true" />}</span>
              {o.label}
            </button>
          ))}
        </>
      ) : (
        <>
          {Object.entries(views).map(([key, v]) => (
            <button key={key} type="button" role="menuitem" aria-haspopup="menu" className={styles.row} onClick={() => setView(key)}>
              <span>{v.title}</span>
              <span className={styles.value}>
                {v.value} <ChevronRight size={16} aria-hidden="true" />
              </span>
            </button>
          ))}
          <button type="button" role="menuitem" className={styles.row} onClick={onHelp}>
            <span>{t('menu.shortcuts')}</span>
            <span className={styles.value}>
              <kbd className={styles.kbd}>?</kbd>
            </span>
          </button>
        </>
      )}
    </div>
  );
}

/** "?" — every shortcut the player understands right now (built from the same list as the handler). */
export function ShortcutHelp({ shortcuts, onClose }) {
  const t = useT();
  const closeRef = useRef(null);
  useEffect(() => closeRef.current?.focus(), []);
  return (
    <div className={styles.helpScrim} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className={styles.help} role="dialog" aria-modal="true" aria-labelledby="player-help-title">
        <header className={styles.helpHead}>
          <h2 id="player-help-title">
            <Keyboard size={20} aria-hidden="true" /> {t('menu.shortcuts')}
          </h2>
          <button ref={closeRef} type="button" className={styles.helpClose} onClick={onClose} aria-label={t('menu.closeShortcuts')}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <dl className={styles.helpList}>
          {shortcuts.map((s) => (
            <div key={s.label} className={styles.helpRow}>
              <dt>
                {s.keys.map((k) => (
                  <kbd key={k} className={styles.kbd}>
                    {k}
                  </kbd>
                ))}
              </dt>
              <dd>{s.label}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

const trackShape = PropTypes.shape({ id: PropTypes.number.isRequired, lang: PropTypes.string, name: PropTypes.string });
SettingsMenu.propTypes = {
  tracks: PropTypes.shape({
    quality: PropTypes.arrayOf(PropTypes.shape({ id: PropTypes.number.isRequired, height: PropTypes.number.isRequired })).isRequired,
    qualityId: PropTypes.number,
    playingHeight: PropTypes.number,
    audio: PropTypes.arrayOf(trackShape).isRequired,
    audioId: PropTypes.number,
    text: PropTypes.arrayOf(trackShape).isRequired,
    textId: PropTypes.number,
  }).isRequired,
  speed: PropTypes.number.isRequired,
  speeds: PropTypes.arrayOf(PropTypes.number).isRequired,
  isLive: PropTypes.bool,
  onSelect: PropTypes.func.isRequired,
  onSpeed: PropTypes.func.isRequired,
  onHelp: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};
ShortcutHelp.propTypes = {
  shortcuts: PropTypes.arrayOf(PropTypes.shape({ keys: PropTypes.arrayOf(PropTypes.string).isRequired, label: PropTypes.string.isRequired })).isRequired,
  onClose: PropTypes.func.isRequired,
};
