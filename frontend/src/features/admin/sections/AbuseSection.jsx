import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

const STATUSES = ['open', 'actioned', 'dismissed'];

export default function AbuseSection() {
  const t = useT();
  const [status, setStatus] = useState('open');
  const key = ['admin', 'abuse', status];
  const flags = useQuery({ queryKey: key, queryFn: () => api.call('admin_abuse_flags', { query: { status } }) });
  const resolve = useAdminMutation(
    ({ id, outcome }) => api.call('admin_resolve_flag', { params: { flag_id: id }, body: { outcome } }),
    { invalidate: [['admin', 'abuse']], success: t('abuse.resolved') },
  );
  const columns = [
    { key: 'user_id', label: t('col.user') },
    { key: 'kind', label: t('col.rule') },
    { key: 'score', label: t('col.score') },
    { key: 'details', label: t('col.details') },
    { key: 'first_seen_at', label: t('col.first'), render: (f) => when(f.first_seen_at) },
    { key: 'last_seen_at', label: t('col.last'), render: (f) => when(f.last_seen_at) },
  ];
  return (
    <>
      <div className={styles.toolbar} role="group" aria-label={t('abuse.filter')}>
        {STATUSES.map((value) => (
          <Button key={value} size="sm" variant={status === value ? 'primary' : 'ghost'} onClick={() => setStatus(value)}>{t(`abuse.${value}`)}</Button>
        ))}
      </div>
      <DataTable
        columns={columns}
        rows={flags.data}
        loading={flags.isLoading}
        empty={t('table.empty')}
        actions={status === 'open' ? (f) => (
          <>
            <Button size="sm" variant="danger" onClick={() => resolve.mutate({ id: f.id, outcome: 'actioned' })}>{t('abuse.markActioned')}</Button>
            <Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: f.id, outcome: 'dismissed' })}>{t('abuse.dismiss')}</Button>
          </>
        ) : undefined}
      />
    </>
  );
}
