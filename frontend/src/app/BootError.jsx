import { translate } from '@/core/i18n';
import { messages } from './i18n';

/** Rendered when the feature registry violates its contract — a named error, never a blank page. */
export function BootError({ error }) {
  return (
    <div role="alert" style={{ padding: '2rem', fontFamily: 'ui-monospace, monospace', color: '#ff4d4d' }}>
      <h1 style={{ fontSize: '1.25rem' }}>{error.name}</h1>
      <p>{error.message}</p>
      <p style={{ color: '#aaa' }}>{translate(messages, 'boot.hint')}</p>
    </div>
  );
}
