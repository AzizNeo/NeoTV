import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RotateCw, ShieldOff } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Panel } from '@/shared/components/Page/Page';
import { Badge, DataTable, Pager } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

const ROOT = ['admin', 'drm'];
const PER_PAGE = 25;

export default function DrmSection() {
  const t = useT();
  const [page, setPage] = useState(1);
  const stats = useQuery({ queryKey: [...ROOT, 'stats'], queryFn: () => api.call('drm_stats') });
  const contents = useQuery({
    queryKey: [...ROOT, 'contents', page],
    queryFn: () => api.call('drm_list_contents', { query: { page, per_page: PER_PAGE } }),
    placeholderData: (previous) => previous,
  });
  const policies = useQuery({ queryKey: [...ROOT, 'policies'], queryFn: () => api.call('drm_list_policies') });
  const licenses = useQuery({ queryKey: [...ROOT, 'licenses'], queryFn: () => api.call('drm_active_licenses', { query: { limit: 100 } }) });
  const events = useQuery({ queryKey: [...ROOT, 'events'], queryFn: () => api.call('drm_events', { query: { limit: 50 } }) });

  const rotate = useAdminMutation((c) => api.call('drm_rotate_key', { params: { content_id: c.id } }), {
    invalidate: [ROOT], success: t('drm.rotated'),
  });
  const unprotect = useAdminMutation((c) => api.call('drm_unprotect', { params: { content_id: c.id } }), {
    invalidate: [ROOT], success: t('drm.unprotected'),
  });
  const revoke = useAdminMutation((l) => api.call('drm_revoke_license', { params: { license_id: l.id } }), {
    invalidate: [ROOT], success: t('drm.revoked'),
  });
  const policyName = (id) => policies.data?.find((p) => p.id === id)?.name ?? t('drm.defaultPolicy');

  return (
    <>
      {stats.data && (
        <div className={styles.grid}>
          {Object.entries(stats.data).map(([k, v]) => <div key={k} className={styles.stat}><span>{k.replaceAll('_', ' ')}</span><strong>{v}</strong></div>)}
        </div>
      )}
      <Panel title={t('drm.protected')}>
        <DataTable
          loading={contents.isLoading}
          rows={contents.data?.items}
          columns={[
            { key: 'content_ref', label: t('col.content'), render: (c) => c.title ?? <span className={styles.mono}>{c.content_ref}</span> },
            { key: 'systems', label: t('col.systems'), render: (c) => c.systems.join(', ') },
            { key: 'policy_id', label: t('col.policy'), render: (c) => policyName(c.policy_id) },
            { key: 'active_licenses', label: t('col.activeLicenses') },
            { key: 'key_rotated_at', label: t('col.keyRotated'), render: (c) => when(c.key_rotated_at) },
          ]}
          actions={(c) => (
            <>
              <Button size="sm" variant="ghost" aria-label={t('drm.rotate')} onClick={() => rotate.mutate(c)}><RotateCw size={16} /></Button>
              <Button size="sm" variant="ghost" aria-label={t('drm.unprotect')} onClick={() => unprotect.mutate(c)}><ShieldOff size={16} /></Button>
            </>
          )}
        />
        {contents.data && <Pager page={page} perPage={PER_PAGE} total={contents.data.total} onPage={setPage} />}
      </Panel>
      <Panel title={t('drm.policies')}>
        <DataTable
          loading={policies.isLoading}
          rows={policies.data}
          columns={[
            { key: 'name', label: t('col.name'), render: (p) => <>{p.name} {p.is_default && <Badge ok>{t('drm.defaultPolicy')}</Badge>}</> },
            { key: 'max_resolution', label: t('col.maxResolution') },
            { key: 'license_duration_s', label: t('col.licenseDuration') },
            { key: 'allow_offline', label: t('col.offline'), render: (p) => (p.allow_offline ? t('drm.hours', { h: p.offline_validity_h }) : t('drm.no')) },
            { key: 'allowed_device_classes', label: t('col.devices'), render: (p) => p.allowed_device_classes.join(', ') },
          ]}
        />
      </Panel>
      <Panel title={t('drm.licenses')}>
        <DataTable
          loading={licenses.isLoading}
          rows={licenses.data}
          columns={[
            { key: 'user_id', label: t('col.user') },
            { key: 'content_ref', label: t('col.content'), render: (l) => <span className={styles.mono}>{l.content_ref}</span> },
            { key: 'system', label: t('col.system') },
            { key: 'renewals', label: t('col.renewals') },
            { key: 'expires_at', label: t('col.expires'), render: (l) => when(l.expires_at) },
          ]}
          actions={(l) => <Button size="sm" variant="danger" onClick={() => revoke.mutate(l)}>{t('drm.revoke')}</Button>}
        />
      </Panel>
      <Panel title={t('drm.events')}>
        <DataTable
          loading={events.isLoading}
          rows={events.data}
          columns={[
            { key: 'created_at', label: t('col.time'), render: (e) => when(e.created_at) },
            { key: 'event_type', label: t('col.event') },
            { key: 'user_id', label: t('col.user') },
            { key: 'content_ref', label: t('col.content') },
            { key: 'error_code', label: t('col.errorCode') },
          ]}
        />
      </Panel>
    </>
  );
}
