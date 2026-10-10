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

const ROOT = ['admin', 'drm'];
const PER_PAGE = 25;

export default function DrmSection() {
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
    invalidate: [ROOT], success: 'İçerik anahtarı yenilendi; açık lisanslar iptal edildi.',
  });
  const unprotect = useAdminMutation((c) => api.call('drm_unprotect', { params: { content_id: c.id } }), {
    invalidate: [ROOT], success: 'Koruma kaldırıldı.',
  });
  const revoke = useAdminMutation((l) => api.call('drm_revoke_license', { params: { license_id: l.id } }), {
    invalidate: [ROOT], success: 'Lisans iptal edildi.',
  });
  const policyName = (id) => policies.data?.find((p) => p.id === id)?.name ?? 'Varsayılan';

  return (
    <>
      {stats.data && (
        <div className={styles.grid}>
          {Object.entries(stats.data).map(([k, v]) => <div key={k} className={styles.stat}><span>{k.replaceAll('_', ' ')}</span><strong>{v}</strong></div>)}
        </div>
      )}
      <Panel title="Korumalı içerikler">
        <DataTable
          loading={contents.isLoading}
          rows={contents.data?.items}
          columns={[
            { key: 'content_ref', label: 'İçerik', render: (c) => c.title ?? <span className={styles.mono}>{c.content_ref}</span> },
            { key: 'systems', label: 'Sistemler', render: (c) => c.systems.join(', ') },
            { key: 'policy_id', label: 'Politika', render: (c) => policyName(c.policy_id) },
            { key: 'active_licenses', label: 'Aktif lisans' },
            { key: 'key_rotated_at', label: 'Anahtar yenileme', render: (c) => when(c.key_rotated_at) },
          ]}
          actions={(c) => (
            <>
              <Button size="sm" variant="ghost" aria-label="Anahtarı yenile" onClick={() => rotate.mutate(c)}><RotateCw size={16} /></Button>
              <Button size="sm" variant="ghost" aria-label="Korumayı kaldır" onClick={() => unprotect.mutate(c)}><ShieldOff size={16} /></Button>
            </>
          )}
        />
        {contents.data && <Pager page={page} perPage={PER_PAGE} total={contents.data.total} onPage={setPage} />}
      </Panel>
      <Panel title="Politikalar">
        <DataTable
          loading={policies.isLoading}
          rows={policies.data}
          columns={[
            { key: 'name', label: 'Ad', render: (p) => <>{p.name} {p.is_default && <Badge ok>Varsayılan</Badge>}</> },
            { key: 'max_resolution', label: 'Azami çözünürlük' },
            { key: 'license_duration_s', label: 'Lisans süresi (sn)' },
            { key: 'allow_offline', label: 'Çevrimdışı', render: (p) => (p.allow_offline ? `${p.offline_validity_h} sa` : 'Hayır') },
            { key: 'allowed_device_classes', label: 'Cihazlar', render: (p) => p.allowed_device_classes.join(', ') },
          ]}
        />
      </Panel>
      <Panel title="Aktif lisanslar">
        <DataTable
          loading={licenses.isLoading}
          rows={licenses.data}
          columns={[
            { key: 'user_id', label: 'Kullanıcı' },
            { key: 'content_ref', label: 'İçerik', render: (l) => <span className={styles.mono}>{l.content_ref}</span> },
            { key: 'system', label: 'Sistem' },
            { key: 'renewals', label: 'Yenileme' },
            { key: 'expires_at', label: 'Bitiş', render: (l) => when(l.expires_at) },
          ]}
          actions={(l) => <Button size="sm" variant="danger" onClick={() => revoke.mutate(l)}>İptal et</Button>}
        />
      </Panel>
      <Panel title="Son olaylar">
        <DataTable
          loading={events.isLoading}
          rows={events.data}
          columns={[
            { key: 'created_at', label: 'Zaman', render: (e) => when(e.created_at) },
            { key: 'event_type', label: 'Olay' },
            { key: 'user_id', label: 'Kullanıcı' },
            { key: 'content_ref', label: 'İçerik' },
            { key: 'error_code', label: 'Hata kodu' },
          ]}
        />
      </Panel>
    </>
  );
}
