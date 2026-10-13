import { describe, expect, it, vi, afterEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { makeQueue, step } from './queue';
import { UpNext } from './components/QueueParts';

const a = { ref: 'c:1', title: 'A' };
const b = { ref: 'c:2', title: 'B' };
const c = { ref: 'c:3', title: 'C' };

describe('play queue', () => {
  it('positions the picked item; a lone item is a queue of one; an outsider is prepended', () => {
    expect(makeQueue(b, [a, b, c])).toMatchObject({ index: 1, autoNext: true });
    expect(makeQueue(a, undefined).items).toEqual([a]);
    expect(makeQueue({ ref: 'x:9', title: 'X' }, [a, b]).items.map((i) => i.ref)).toEqual(['x:9', 'c:1', 'c:2']);
  });

  it('on demand stops at the ends; live TV wraps around', () => {
    const q = makeQueue(c, [a, b, c]);
    expect(step(q, 1, { wrap: false })).toBeNull();
    expect(step(q, -1, { wrap: false })).toBe(1);
    expect(step(q, 1, { wrap: true })).toBe(0);
    expect(step(makeQueue(a, [a, b, c]), -1, { wrap: true })).toBe(2);
    expect(step(makeQueue(a, [a]), 1, { wrap: true })).toBeNull();
  });
});

describe('UpNext', () => {
  afterEach(() => vi.useRealTimers());

  it('plays the next episode when the countdown runs out, unless cancelled first', () => {
    vi.useFakeTimers();
    const onPlay = vi.fn();
    render(<UpNext item={{ ref: 'c:2', title: 'Dizi', subtitle: 'S1 B2' }} onPlay={onPlay} onCancel={() => {}} />);
    expect(screen.getByText(/10 sn/)).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(9000));
    expect(onPlay).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1000));
    expect(onPlay).toHaveBeenCalledTimes(1);
  });
});
