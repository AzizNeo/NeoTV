import { describe, expect, it } from 'vitest';
import { nextUp, remaining } from './nextUp';

const ep = (number, ref, available = true) => ({ number, name: `E${number}`, play_ref: ref, available });
const series = (...seasons) => ({ card: { kind: 'series', available: true }, play_ref: null, seasons });
const progress = (entries) => new Map(entries.map(([ref, completed, at]) => [ref, { completed, updated_at: at, position_s: 300, duration_s: 900 }]));

describe('nextUp', () => {
  const show = series(
    { number: 1, episodes: [ep(1, 'c:1'), ep(2, 'c:2')] },
    { number: 2, episodes: [ep(1, 'c:3', false), ep(2, 'c:4')] },
  );

  it('movie: resume when started, play otherwise, nothing when unavailable', () => {
    const movie = { card: { kind: 'movie', available: true }, play_ref: 'c:9', seasons: [] };
    expect(nextUp(movie, new Map())).toMatchObject({ ref: 'c:9', label: 'Oynat', resume: false });
    expect(nextUp(movie, progress([['c:9', false, '2026-01-01']]))).toMatchObject({ label: 'Devam et', resume: true });
    expect(nextUp({ ...movie, card: { kind: 'movie', available: false } }, new Map())).toBeNull();
  });

  it('series: first available episode when nothing was watched', () => {
    expect(nextUp(show, new Map())).toMatchObject({ ref: 'c:1', label: 'Oynat: S1 B1', season: 1 });
  });

  it('series: resumes the most recently watched unfinished episode', () => {
    const p = progress([['c:1', true, '2026-01-01'], ['c:2', false, '2026-01-02']]);
    expect(nextUp(show, p)).toMatchObject({ ref: 'c:2', label: 'Devam et: S1 B2', resume: true });
  });

  it('series: after a finished episode, the next *available* one (skips unplayable)', () => {
    const p = progress([['c:2', true, '2026-01-03'], ['c:1', false, '2026-01-01']]);
    expect(nextUp(show, p)).toMatchObject({ ref: 'c:4', label: 'Oynat: S2 B2', season: 2 });
  });

  it('series: finished the last episode → start over from the first', () => {
    expect(nextUp(show, progress([['c:4', true, '2026-01-05']]))).toMatchObject({ ref: 'c:1' });
  });
});

describe('remaining', () => {
  it('rounds to whole minutes and is silent for finished or unknown items', () => {
    expect(remaining({ completed: false, position_s: 300, duration_s: 900 })).toBe('10 dk kaldı');
    expect(remaining({ completed: true, position_s: 900, duration_s: 900 })).toBeNull();
    expect(remaining(undefined)).toBeNull();
  });
});
