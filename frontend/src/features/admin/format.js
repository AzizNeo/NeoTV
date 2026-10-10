/** Short Turkish date-time for back-office tables; '—' for empty values. */
export const when = (iso) => (iso ? new Date(iso).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : '—');
