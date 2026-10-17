import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Panel } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { when } from '../format';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

// Dashboard groups are optional on the backend (null when that module is off).
const GROUPS = ['users', 'sessions', 'plans', 'catalog', 'live', 'devices', 'drm'];

export default function OverviewSection() {
  const t = useT();
  const stats = useQuery({ queryKey: ['admin', 'stats'], queryFn: () => api.call('admin_stats'), refetchInterval: 30_000 });
  // Plan rows are keyed by plan id; their label is the plan's name from the catalogue (new plans need no
  // translation). Only fetched when the dashboard has a plans group, i.e. billing is on.
  const plans = useQuery({
    queryKey: ['admin', 'plan-names'],
    queryFn: () => api.call('billing_plans'),
    enabled: Boolean(stats.data?.plans),
    staleTime: 3_600_000,
  });
  // A figure without a label shows its message id (and warns in development) — visible, never silent.
  const label = (group, name) =>
    group === 'plans' ? (plans.data?.find((plan) => plan.id === name)?.display_name ?? name) : t(`stats.${group}.${name}`);
  if (stats.isLoading) return <Spinner />;
  if (!stats.data) return null;
  return (
    <>
      {GROUPS.filter((key) => stats.data[key]).map((key) => (
        <Panel key={key} title={t(`groups.${key}`)}>
          <div className={styles.grid}>
            {Object.entries(stats.data[key]).map(([name, value]) => (
              <div key={name} className={styles.stat}><span>{label(key, name)}</span><strong>{value}</strong></div>
            ))}
          </div>
        </Panel>
      ))}
      <small>{t('updated', { when: when(stats.data.generated_at) })}</small>
    </>
  );
}
