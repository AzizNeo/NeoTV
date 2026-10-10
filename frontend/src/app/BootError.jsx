/** Rendered when the feature registry violates its contract — a named error, never a blank page. */
export function BootError({ error }) {
  return (
    <div role="alert" style={{ padding: '2rem', fontFamily: 'ui-monospace, monospace', color: '#ff4d4d' }}>
      <h1 style={{ fontSize: '1.25rem' }}>{error.name}</h1>
      <p>{error.message}</p>
      <p style={{ color: '#aaa' }}>src/features/index.js, manifest dosyaları veya VITE_DISABLED_FEATURES değerini kontrol edin.</p>
    </div>
  );
}
