import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';

const STATUSES = [['open', 'Açık'], ['actioned', 'İşlem yapıldı'], ['dismissed', 'Yok sayıldı']];

export default function AbuseSection() {
  const [status, setStatus] = useState('open');
  const key = ['admin', 'abuse', status];
  const flags = useQuery({ queryKey: key, queryFn: () => api.call('admin_abuse_flags', { query: { status } }) });
  const resolve = useAdminMutation(
    ({ id, outcome }) => api.call('admin_resolve_flag', { params: { flag_id: id }, body: { outcome } }),
    { invalidate: [['admin', 'abuse']], success: 'İşaret kapatıldı.' },
  );
  const columns = [
    { key: 'user_id', label: 'Kullanıcı' },
    { key: 'kind', label: 'Kural' },
    { key: 'score', label: 'Skor' },
    { key: 'details', label: 'Ayrıntı' },
    { key: 'first_seen_at', label: 'İlk', render: (f) => when(f.first_seen_at) },
    { key: 'last_seen_at', label: 'Son', render: (f) => when(f.last_seen_at) },
  ];
  return (
    <>
      <div className={styles.toolbar} role="group" aria-label="Durum filtresi">
        {STATUSES.map(([value, label]) => (
          <Button key={value} size="sm" variant={status === value ? 'primary' : 'ghost'} onClick={() => setStatus(value)}>{label}</Button>
        ))}
      </div>
      <DataTable
        columns={columns}
        rows={flags.data}
        loading={flags.isLoading}
        empty="Kayıt yok"
        actions={status === 'open' ? (f) => (
          <>
            <Button size="sm" variant="danger" onClick={() => resolve.mutate({ id: f.id, outcome: 'actioned' })}>İşlem yapıldı</Button>
            <Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: f.id, outcome: 'dismissed' })}>Yok say</Button>
          </>
        ) : undefined}
      />
    </>
  );
}
