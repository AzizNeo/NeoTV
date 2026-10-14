import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

const KEY = ['admin', 'sessions'];

export default function SessionsSection() {
  const t = useT();
  const sessions = useQuery({ queryKey: KEY, queryFn: () => api.call('admin_live_sessions'), refetchInterval: 15_000 });
  const terminate = useAdminMutation(
    (s) => api.call('admin_terminate', { params: { token: s.token } }),
    { invalidate: [KEY], success: t('sessions.terminated') },
  );
  const columns = [
    { key: 'user_id', label: t('col.user') },
    { key: 'profile_id', label: t('col.profile') },
    { key: 'content_ref', label: t('col.content'), render: (s) => <span className={styles.mono}>{s.content_ref}</span> },
    { key: 'ip', label: t('col.ip') },
    { key: 'started_at', label: t('col.started'), render: (s) => when(s.started_at) },
    { key: 'last_heartbeat_at', label: t('col.heartbeat'), render: (s) => when(s.last_heartbeat_at) },
  ];
  return (
    <DataTable
      columns={columns}
      rows={sessions.data}
      rowKey="token"
      loading={sessions.isLoading}
      empty={t('sessions.empty')}
      actions={(s) => <Button size="sm" variant="danger" disabled={terminate.isPending} onClick={() => terminate.mutate(s)}>{t('sessions.terminate')}</Button>}
    />
  );
}
