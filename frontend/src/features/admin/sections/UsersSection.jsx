import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Badge, DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

const KEY = ['admin', 'users'];

export default function UsersSection() {
  const t = useT();
  const [cursors, setCursors] = useState([null]); // keyset pagination: stack of cursors
  const cursor = cursors.at(-1);
  const users = useQuery({
    queryKey: [...KEY, cursor],
    queryFn: () => api.call('admin_users', { query: { cursor: cursor ?? undefined, limit: 50 } }),
  });
  const toggle = useAdminMutation(
    (u) => api.call(u.is_active ? 'admin_suspend' : 'admin_activate', { params: { user_id: u.id } }),
    { invalidate: [KEY], success: (u) => t(u.is_active ? 'users.activated' : 'users.wasSuspended', { name: u.username }) },
  );
  const columns = [
    { key: 'username', label: t('col.user') },
    { key: 'email', label: t('col.email') },
    { key: 'role', label: t('col.role') },
    { key: 'plan', label: t('col.plan') },
    { key: 'active_sessions', label: t('col.openStreams') },
    { key: 'is_active', label: t('col.status'), render: (u) => <Badge ok={u.is_active}>{t(u.is_active ? 'users.active' : 'users.suspended')}</Badge> },
    { key: 'last_login_at', label: t('col.lastLogin'), render: (u) => when(u.last_login_at) },
  ];
  return (
    <>
      <DataTable
        columns={columns}
        rows={users.data?.items}
        loading={users.isLoading}
        actions={(u) => (
          <Button size="sm" variant={u.is_active ? 'danger' : 'secondary'} disabled={toggle.isPending} onClick={() => toggle.mutate(u)}>
            {t(u.is_active ? 'users.suspend' : 'users.activate')}
          </Button>
        )}
      />
      <div className={styles.pager}>
        <Button variant="ghost" size="sm" disabled={cursors.length <= 1} onClick={() => setCursors((c) => c.slice(0, -1))}>{t('table.prev')}</Button>
        <Button variant="ghost" size="sm" disabled={!users.data?.next_cursor} onClick={() => setCursors((c) => [...c, users.data.next_cursor])}>{t('table.next')}</Button>
      </div>
    </>
  );
}
