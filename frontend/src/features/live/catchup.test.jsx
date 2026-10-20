import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { catchupAction } from './catchup';
import { GuideGrid } from './pages/GuideGrid';

const NOW = Date.parse('2026-10-20T18:10:00Z');
const at = (minutes) => new Date(NOW + minutes * 60_000).toISOString();
const ARCHIVED = { id: 1, ref: 'live:1', name: 'Haber', catchup_days: 3 };
const PLAIN = { id: 2, ref: 'live:2', name: 'Müzik', catchup_days: 0 };
const program = (id, channel, from, to, title) => ({ id, channel_id: channel, starts_at: at(from), ends_at: at(to), title, description: null });

describe('catchupAction', () => {
  it('offers start over while a programme airs and catch-up once it is over, within the channel window', () => {
    expect(catchupAction(ARCHIVED, program(1, 1, -10, 20, 'a'), NOW)).toEqual({ kind: 'startOver', window: { start: at(-10), end: at(20) } });
    expect(catchupAction(ARCHIVED, program(2, 1, -70, -10, 'b'), NOW)).toEqual({ kind: 'catchup', window: { start: at(-70), end: at(-10) } });
    expect(catchupAction(ARCHIVED, program(3, 1, 5, 60, 'c'), NOW)).toBeNull(); // not started
    expect(catchupAction(ARCHIVED, program(4, 1, -4 * 1440, -4 * 1440 + 30, 'd'), NOW)).toBeNull(); // older than 3 days
    expect(catchupAction(PLAIN, program(5, 2, -70, -10, 'e'), NOW)).toBeNull(); // not archived
  });

  it('never asks for more than the 6 hours one session plays', () => {
    const long = catchupAction(ARCHIVED, program(6, 1, -600, -10, 'marathon'), NOW);
    expect(Date.parse(long.window.end) - Date.parse(long.window.start)).toBe(6 * 3_600_000);
  });
});

describe('the guide with catch-up', () => {
  it('makes past programmes of an archived channel playable, with a window', () => {
    vi.useFakeTimers({ now: NOW, toFake: ['Date'] });
    const onCatchup = vi.fn();
    render(
      <GuideGrid
        channels={[ARCHIVED, PLAIN]}
        programs={[program(1, 1, -70, -10, 'Sabah Haberleri'), program(2, 2, -70, -10, 'Klip'), program(3, 1, -10, 50, 'Öğle')]}
        onSelect={vi.fn()}
        onCatchup={onCatchup}
        back={3}
      />,
    );
    vi.useRealTimers();
    fireEvent.click(screen.getByRole('button', { name: /^Sabah Haberleri \d{2}:\d{2}–\d{2}:\d{2}, tekrar izle \(Haber\)$/ }));
    expect(onCatchup).toHaveBeenCalledWith({ ref: 'live:1', title: 'Sabah Haberleri', subtitle: 'Haber', window: { start: at(-70), end: at(-10) } });
    expect(screen.getByRole('button', { name: /^Öğle \d{2}:\d{2}–\d{2}:\d{2}, baştan başlat \(Haber\)$/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Klip/ })).toBeNull(); // the music channel has no archive
  });
});
