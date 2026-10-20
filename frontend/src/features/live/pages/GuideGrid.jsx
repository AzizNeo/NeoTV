import PropTypes from 'prop-types';
import { useEffect, useRef, useState } from 'react';
import { History, RotateCcw } from 'lucide-react';
import styles from './GuideGrid.module.css';
import { useFormat } from '@/core/i18n';
import { useT } from '../i18n';
import { catchupAction } from '../catchup';

const HOUR_PX = 240;
const MIN_TARGET_PX = 24;
/** Horizontal programme guide: one lane per channel, blocks positioned by time. */
/** Wall clock as state (render stays pure); ticks once a minute so the now-line moves. */
function useNow(intervalMs = 60_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

export function GuideGrid({ channels, programs, onSelect, onCatchup, hours = 6, back = 0 }) {
  const t = useT();
  const { time } = useFormat();
  const now = useNow();
  const scroller = useRef(null);
  const start = new Date(now - back * 3_600_000);
  start.setMinutes(start.getMinutes() < 30 ? 0 : 30, 0, 0);
  const startMs = start.getTime();
  const span = hours + back;
  const endMs = startMs + span * 3_600_000;
  // With past hours shown, open at "now" (the past is a scroll to the left away).
  useEffect(() => {
    if (back > 0 && scroller.current) scroller.current.scrollLeft = Math.max(0, ((Date.now() - startMs) / 3_600_000) * HOUR_PX - HOUR_PX / 2);
  }, [back, startMs]);
  const byChannel = new Map();
  for (const p of programs) {
    const list = byChannel.get(p.channel_id) ?? [];
    list.push(p);
    byChannel.set(p.channel_id, list);
  }
  const offset = (ms) => ((ms - startMs) / 3_600_000) * HOUR_PX;
  const slots = Array.from({ length: span * 2 }, (_, i) => new Date(startMs + i * 1_800_000));

  return (
    <section className={styles.guide} aria-label={t('guide')}>
      <h2>{t('guide')}</h2>
      <div className={styles.scroller} ref={scroller}>
        <div className={styles.timeline} style={{ width: span * HOUR_PX }}>
          {slots.map((slot) => (
            <span key={slot.getTime()} style={{ left: offset(slot.getTime()) }}>
              {time(slot)}
            </span>
          ))}
          {now > startMs && now < endMs && <span className={styles.now} style={{ left: offset(now) }} aria-hidden="true" />}
        </div>
        {channels.map((channel) => (
          <div key={channel.id} className={styles.lane}>
            <button className={styles.channel} onClick={() => onSelect({ ref: channel.ref, title: channel.name })} title={t('watch', { name: channel.name })}>
              {channel.name}
            </button>
            <div className={styles.track} style={{ width: span * HOUR_PX }}>
              {(byChannel.get(channel.id) ?? [])
                .filter((p) => new Date(p.ends_at).getTime() > startMs && new Date(p.starts_at).getTime() < endMs)
                .map((p) => {
                  const s = Math.max(startMs, new Date(p.starts_at).getTime());
                  const e = Math.min(endMs, new Date(p.ends_at).getTime());
                  const airing = now >= new Date(p.starts_at).getTime() && now < new Date(p.ends_at).getTime();
                  const past = new Date(p.ends_at).getTime() <= now;
                  // WCAG 2.5.8 (target size): a block clipped to a sliver at the grid's edge is not a
                  // usable target for anyone, so it stays plain text; the rest of the programme is gone.
                  const wide = offset(e) - offset(s) - 2 >= MIN_TARGET_PX;
                  const action = onCatchup && wide ? catchupAction(channel, p, now) : null;
                  const className = `${styles.program} ${airing ? styles.airing : ''} ${past ? styles.past : ''} ${action ? styles.playable : ''}`;
                  const style = { left: offset(s), width: Math.max(2, offset(e) - offset(s) - 2) };
                  // The action is read after the visible text, so the accessible name contains what is
                  // seen (WCAG 2.5.3, label in name): "Test Card 10:00–10:30, watch again (Akamai Live)".
                  const body = (
                    <>
                      <strong>
                        {action && (action.kind === 'startOver' ? <RotateCcw size={12} aria-hidden="true" /> : <History size={12} aria-hidden="true" />)} {p.title}
                      </strong>{' '}
                      <small>
                        {time(p.starts_at)}–
                        {time(p.ends_at)}
                      </small>
                      {action && <span className="visually-hidden">{t(action.kind, { channel: channel.name })}</span>}
                    </>
                  );
                  return action ? (
                    <button
                      key={p.id}
                      type="button"
                      className={className}
                      style={style}
                      title={p.description ?? p.title}
                      onClick={() => onCatchup({ ref: channel.ref, title: p.title, subtitle: channel.name, window: action.window })}
                    >
                      {body}
                    </button>
                  ) : (
                    <div key={p.id} className={className} style={style} title={p.description ?? p.title}>
                      {body}
                    </div>
                  );
                })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

GuideGrid.propTypes = {
  channels: PropTypes.arrayOf(PropTypes.object).isRequired,
  programs: PropTypes.arrayOf(PropTypes.object).isRequired,
  onSelect: PropTypes.func.isRequired,
  onCatchup: PropTypes.func,
  hours: PropTypes.number,
  back: PropTypes.number,
};
