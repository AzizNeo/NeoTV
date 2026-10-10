import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';

const KEY = ['admin', 'sessions'];

export default function SessionsSection() {
  const sessions = useQuery({ queryKey: KEY, queryFn: () => api.call('admin_live_sessions'), refetchInterval: 15_000 });
  const terminate = useAdminMutation(
    (s) => api.call('admin_terminate', { params: { token: s.token } }),
    { invalidate: [KEY], success: 'Yayın oturumu sonlandırıldı.' },
  );
  const columns = [
    { key: 'user_id', label: 'Kullanıcı' },
    { key: 'profile_id', label: 'Profil' },
    { key: 'content_ref', label: 'İçerik', render: (s) => <span className={styles.mono}>{s.content_ref}</span> },
    { key: 'ip', label: 'IP' },
    { key: 'started_at', label: 'Başlangıç', render: (s) => when(s.started_at) },
    { key: 'last_heartbeat_at', label: 'Son sinyal', render: (s) => when(s.last_heartbeat_at) },
  ];
  return (
    <DataTable
      columns={columns}
      rows={sessions.data}
      rowKey="token"
      loading={sessions.isLoading}
      empty="Açık yayın oturumu yok"
      actions={(s) => <Button size="sm" variant="danger" disabled={terminate.isPending} onClick={() => terminate.mutate(s)}>Sonlandır</Button>}
    />
  );
}
