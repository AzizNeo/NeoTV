import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Laptop, Monitor, Pencil, ShieldCheck, ShieldOff, Smartphone, Tablet, Trash2, Tv } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Modal } from '@/shared/components/Modal/Modal';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useToast } from '@/shared/components/Toast/Toast';
import styles from './DevicesPage.module.css';
import { useFormat } from '@/core/i18n';
import { useT } from '../i18n';

const ICON = { desktop: Laptop, mobile: Smartphone, tablet: Tablet, tv: Tv };
const KEY = ['devices'];

export default function DevicesPage() {
  const t = useT();
  const { dateTime } = useFormat();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [renaming, setRenaming] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const devices = useQuery({ queryKey: KEY, queryFn: () => api.call('devices_list_devices') });
  const done = (message) => () => {
    if (message) toast.success(message);
    queryClient.invalidateQueries({ queryKey: KEY });
  };
  const onError = (err) => toast.error(err.userMessage);

  const trust = useMutation({
    mutationFn: (d) => api.call(d.is_trusted ? 'devices_untrust' : 'devices_trust', { params: { device_id: d.id } }),
    onSuccess: done(),
    onError,
  });
  const rename = useMutation({
    mutationFn: ({ id, name }) => api.call('devices_rename', { params: { device_id: id }, body: { name } }),
    onSuccess: () => { setRenaming(null); done(t('renamed'))(); },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (d) => api.call('devices_revoke_device', { params: { device_id: d.id } }),
    onSuccess: () => { setRevoking(null); done(t('revoked'))(); },
    onError,
  });

  if (devices.isLoading) return <Spinner fullScreen />;
  return (
    <Page title={t('title')} subtitle={t('subtitle')}>
      {!devices.data?.length ? (
        <EmptyState icon={Monitor} title={t('empty')} />
      ) : (
        <ul className={styles.list}>
          {devices.data.map((d) => {
            const Icon = ICON[d.device_type] ?? Monitor;
            return (
              <li key={d.id} className={`${styles.item} ${d.is_current ? styles.current : ''}`}>
                <Icon size={28} aria-hidden="true" className={styles.icon} />
                <div className={styles.body}>
                  <strong>
                    {d.name} {d.is_current && <span className={styles.badge}>{t('current')}</span>}
                    {d.is_trusted && <span className={styles.trusted}>{t('trusted')}</span>}
                  </strong>
                  <small>
                    {[d.browser, d.os].filter(Boolean).join(' · ')} · {t('lastSeen', { when: dateTime(d.last_seen_at) })}
                    {d.last_ip ? ` · ${d.last_ip}` : ''} · {t('logins', { count: d.login_count })}
                  </small>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setRenaming({ id: d.id, name: d.name })} aria-label={t('rename')}><Pencil size={16} /></Button>
                <Button variant="ghost" size="sm" onClick={() => trust.mutate(d)} aria-label={t(d.is_trusted ? 'untrust' : 'trust')}>
                  {d.is_trusted ? <ShieldOff size={16} /> : <ShieldCheck size={16} />}
                </Button>
                {!d.is_current && (
                  <Button variant="ghost" size="sm" onClick={() => setRevoking(d)} aria-label={t('revoke')}><Trash2 size={16} /></Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <Modal isOpen={Boolean(renaming)} onClose={() => setRenaming(null)} title={t('renameTitle')}>
        <form onSubmit={(e) => { e.preventDefault(); rename.mutate(renaming); }} style={{ display: 'grid', gap: '0.75rem' }}>
          <input className="input-field" maxLength={100} value={renaming?.name ?? ''} onChange={(e) => setRenaming((r) => ({ ...r, name: e.target.value }))} aria-label={t('name')} autoFocus />
          <Button type="submit" disabled={!renaming?.name?.trim() || rename.isPending}>{t('save')}</Button>
        </form>
      </Modal>
      <Modal isOpen={Boolean(revoking)} onClose={() => setRevoking(null)} title={t('revoke')}>
        <p>{t('revokeBody', { name: revoking?.name ?? '' })}</p>
        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={() => setRevoking(null)}>{t('cancel')}</Button>
          <Button variant="danger" onClick={() => revoke.mutate(revoking)} disabled={revoke.isPending}>{t('revoke')}</Button>
        </div>
      </Modal>
    </Page>
  );
}
