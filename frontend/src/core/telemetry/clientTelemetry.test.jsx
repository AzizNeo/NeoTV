import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { ErrorBoundary } from '@/shared/components/ErrorBoundary/ErrorBoundary';
import { createReporter, MAX_BATCH, MAX_ERRORS } from './clientTelemetry';

const TRACE = '4bf92f3577b34da6a3ce929d0e0e4736';
const setup = () => {
  const sent = [];
  const reporter = createReporter({ send: (events) => sent.push(events), path: () => '/title/sintel', release: '2.0.0' });
  return { reporter, sent, all: () => sent.flat() };
};

describe('browser telemetry reporter', () => {
  it('queues vitals and sends them on flush', () => {
    const { reporter, sent } = setup();
    reporter.vital({ name: 'LCP', value: 1800, rating: 'good' });
    expect(sent).toEqual([]);
    reporter.flush();
    expect(sent).toEqual([[{ kind: 'vital', name: 'LCP', value: 1800, rating: 'good' }]]);
    reporter.flush();
    expect(sent).toHaveLength(1); // nothing left
  });

  it('sends in batches the API accepts', () => {
    const { reporter, sent } = setup();
    for (let i = 0; i < MAX_BATCH * 2 + 3; i += 1) reporter.vital({ name: 'CLS', value: 0.01, rating: 'good' });
    reporter.flush();
    expect(sent.map((batch) => batch.length)).toEqual([MAX_BATCH, MAX_BATCH, 3]);
  });

  it('reports an error with the path only, the release and the API trace id', () => {
    const { reporter, all } = setup();
    const apiError = Object.assign(new Error('Wrong username or password'), { traceId: TRACE });
    reporter.error('unhandledrejection', apiError);
    reporter.flush();
    const [event] = all();
    expect(event).toMatchObject({ kind: 'error', source: 'unhandledrejection', path: '/title/sintel', release: '2.0.0', trace_id: TRACE });
    expect(event.message).toBe('Wrong username or password');
  });

  it('never floods: each distinct error once, at most MAX_ERRORS per page', () => {
    const { reporter, all } = setup();
    for (let i = 0; i < 50; i += 1) reporter.error('error', new Error('same crash loop'));
    for (let i = 0; i < 50; i += 1) reporter.error('error', new Error(`distinct ${i}`));
    reporter.flush();
    expect(all().filter((e) => e.message === 'same crash loop')).toHaveLength(1);
    expect(all()).toHaveLength(MAX_ERRORS);
  });

  it('drops opaque cross-origin errors and invalid trace ids', () => {
    const { reporter, all } = setup();
    reporter.error('error', 'Script error.');
    reporter.error('error', Object.assign(new Error('x'), { traceId: 'not-hex' }));
    reporter.flush();
    expect(all()).toHaveLength(1);
    expect(all()[0].trace_id).toBeNull();
  });

  it('a failing transport never throws into the page', () => {
    const reporter = createReporter({ send: () => { throw new Error('beacon refused'); }, path: () => '/' });
    reporter.vital({ name: 'FCP', value: 900, rating: 'good' });
    expect(() => reporter.flush()).not.toThrow();
  });
});

describe('ErrorBoundary announces render errors for telemetry', () => {
  it('dispatches app:render-error with the error (shared/ never imports core/)', () => {
    const seen = vi.fn();
    window.addEventListener('app:render-error', seen);
    const Boom = () => { throw new Error('render exploded'); };
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary labels={{ title: 't', unknown: 'u', reload: 'r' }}><Boom /></ErrorBoundary>);
    window.removeEventListener('app:render-error', seen);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen.mock.calls[0][0].detail.error.message).toBe('render exploded');
  });
});
