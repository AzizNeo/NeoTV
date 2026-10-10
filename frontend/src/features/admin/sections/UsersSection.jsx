import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Badge, DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';

const KEY = ['admin', 'users'];

export default function UsersSection() {
  const [cursors, setCursors] = useState([null]); // keyset pagination: stack of cursors
  const cursor = cursors.at(-1);
  const users = useQuery({
    queryKey: [...KEY, cursor],
    queryFn: () => api.call('admin_users', { query: { cursor: cursor ?? undefined, limit: 50 } }),
  });
  const toggle = useAdminMutation(
    (u) => api.call(u.is_active ? 'admin_suspend' : 'admin_activate', { params: { user_id: u.id } }),
    { invalidate: [KEY], success: (u) => (u.is_active ? `${u.username} etkinleştirildi.` : `${u.username} askıya alındı.`) },
  );
  const columns = [
    { key: 'username', label: 'Kullanıcı' },
    { key: 'email', label: 'E-posta' },
    { key: 'role', label: 'Rol' },
    { key: 'plan', label: 'Plan' },
    { key: 'active_sessions', label: 'Açık yayın' },
    { key: 'is_active', label: 'Durum', render: (u) => <Badge ok={u.is_active}>{u.is_active ? 'Aktif' : 'Askıda'}</Badge> },
    { key: 'last_login_at', label: 'Son giriş', render: (u) => when(u.last_login_at) },
  ];
  return (
    <>
      <DataTable
        columns={columns}
        rows={users.data?.items}
        loading={users.isLoading}
        actions={(u) => (
          <Button size="sm" variant={u.is_active ? 'danger' : 'secondary'} disabled={toggle.isPending} onClick={() => toggle.mutate(u)}>
            {u.is_active ? 'Askıya al' : 'Etkinleştir'}
          </Button>
        )}
      />
      <div className={styles.pager}>
        <Button variant="ghost" size="sm" disabled={cursors.length <= 1} onClick={() => setCursors((c) => c.slice(0, -1))}>‹ Önceki</Button>
        <Button variant="ghost" size="sm" disabled={!users.data?.next_cursor} onClick={() => setCursors((c) => [...c, users.data.next_cursor])}>Sonraki ›</Button>
      </div>
    </>
  );
}
