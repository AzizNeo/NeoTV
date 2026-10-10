import PropTypes from 'prop-types';
import { useEffect, useState } from 'react';
import styles from './GuideGrid.module.css';

const HOUR_PX = 240;

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

export function GuideGrid({ channels, programs, onSelect, hours = 6 }) {
  const now = useNow();
  const start = new Date(now);
  start.setMinutes(start.getMinutes() < 30 ? 0 : 30, 0, 0);
  const startMs = start.getTime();
  const endMs = startMs + hours * 3_600_000;
  const byChannel = new Map();
  for (const p of programs) {
    const list = byChannel.get(p.channel_id) ?? [];
    list.push(p);
    byChannel.set(p.channel_id, list);
  }
  const offset = (ms) => ((ms - startMs) / 3_600_000) * HOUR_PX;
  const slots = Array.from({ length: hours * 2 }, (_, i) => new Date(startMs + i * 1_800_000));

  return (
    <section className={styles.guide} aria-label="Yayın akışı">
      <h2>Yayın akışı</h2>
      <div className={styles.scroller}>
        <div className={styles.timeline} style={{ width: hours * HOUR_PX }}>
          {slots.map((t) => (
            <span key={t.getTime()} style={{ left: offset(t.getTime()) }}>
              {t.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}
            </span>
          ))}
          {now > startMs && now < endMs && <span className={styles.now} style={{ left: offset(now) }} aria-hidden="true" />}
        </div>
        {channels.map((channel) => (
          <div key={channel.id} className={styles.lane}>
            <button className={styles.channel} onClick={() => onSelect({ ref: channel.ref, title: channel.name })} title={`${channel.name} izle`}>
              {channel.name}
            </button>
            <div className={styles.track} style={{ width: hours * HOUR_PX }}>
              {(byChannel.get(channel.id) ?? [])
                .filter((p) => new Date(p.ends_at).getTime() > startMs && new Date(p.starts_at).getTime() < endMs)
                .map((p) => {
                  const s = Math.max(startMs, new Date(p.starts_at).getTime());
                  const e = Math.min(endMs, new Date(p.ends_at).getTime());
                  const airing = now >= new Date(p.starts_at).getTime() && now < new Date(p.ends_at).getTime();
                  return (
                    <div key={p.id} className={`${styles.program} ${airing ? styles.airing : ''}`} style={{ left: offset(s), width: Math.max(2, offset(e) - offset(s) - 2) }} title={p.description ?? p.title}>
                      <strong>{p.title}</strong>
                      <small>
                        {new Date(p.starts_at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}–
                        {new Date(p.ends_at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}
                      </small>
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
  hours: PropTypes.number,
};
