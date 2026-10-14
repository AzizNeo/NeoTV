import { formatDateTime } from '@/core/i18n';

/** Short date-time for back-office tables, in the viewer's language; '—' for empty values. */
export const when = (iso) => formatDateTime(iso, { dateStyle: 'short', timeStyle: 'short' });
