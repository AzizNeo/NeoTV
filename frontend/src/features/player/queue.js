/**
 * Play queue: an ordered list (a series' episodes, a channel list) and a position in it.
 * Pure helpers — the overlay and tests share them.
 */

/** Build the queue state for `play(item, { queue })`; a lone item is a queue of one. */
export function makeQueue(item, list, { autoNext = true } = {}) {
  const items = list?.length ? list : [item];
  const found = items.findIndex((q) => q.ref === item.ref);
  return { items: found === -1 ? [item, ...items] : items, index: Math.max(0, found), autoNext };
}

/**
 * Next position in `dir` (+1/-1). Live TV wraps around (channel up from the last goes to the first);
 * on-demand stops at the ends (returns null).
 */
export function step(queue, dir, { wrap }) {
  const n = queue.items.length;
  if (n < 2) return null;
  const next = queue.index + dir;
  if (wrap) return (next + n) % n;
  return next >= 0 && next < n ? next : null;
}
