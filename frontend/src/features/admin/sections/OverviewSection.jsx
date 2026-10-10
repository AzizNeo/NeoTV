import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Panel } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { when } from '../format';
import styles from '../components/Admin.module.css';

// Dashboard groups are optional on the backend (null when that module is off).
const GROUPS = [
  ['users', 'Kullanıcılar'], ['sessions', 'Oturumlar'], ['plans', 'Planlar'], ['catalog', 'Katalog'],
  ['live', 'Canlı yayın'], ['devices', 'Cihazlar'], ['drm', 'DRM'],
];

export default function OverviewSection() {
  const stats = useQuery({ queryKey: ['admin', 'stats'], queryFn: () => api.call('admin_stats'), refetchInterval: 30_000 });
  if (stats.isLoading) return <Spinner />;
  if (!stats.data) return null;
  return (
    <>
      {GROUPS.filter(([key]) => stats.data[key]).map(([key, title]) => (
        <Panel key={key} title={title}>
          <div className={styles.grid}>
            {Object.entries(stats.data[key]).map(([name, value]) => (
              <div key={name} className={styles.stat}><span>{name.replaceAll('_', ' ')}</span><strong>{value}</strong></div>
            ))}
          </div>
        </Panel>
      ))}
      <small>Güncellendi: {when(stats.data.generated_at)}</small>
    </>
  );
}
