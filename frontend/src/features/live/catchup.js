// Catch-up in the guide (ADR-0012).
const DAY_MS = 86_400_000;
const MAX_WINDOW_MS = 6 * 3_600_000; // the server plays at most 6 hours per catch-up session

/**
 * What a programme block offers (ADR-0012): `startOver` while it airs, `catchup` once it is over —
 * only on a channel with an archive, and only as far back as the channel keeps. The viewer's plan
 * may allow less; the server answers that, with a message.
 */
export function catchupAction(channel, program, now) {
  const days = channel.catchup_days ?? 0;
  const starts = new Date(program.starts_at).getTime();
  const ends = new Date(program.ends_at).getTime();
  if (days <= 0 || starts >= now || starts < now - days * DAY_MS) return null;
  return { kind: ends > now ? 'startOver' : 'catchup', window: { start: program.starts_at, end: new Date(Math.min(ends, starts + MAX_WINDOW_MS)).toISOString() } };
}

