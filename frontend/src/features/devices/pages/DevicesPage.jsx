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

const ICON = { desktop: Laptop, mobile: Smartphone, tablet: Tablet, tv: Tv };
const KEY = ['devices'];
const when = (iso) => new Date(iso).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'short' });

export default function DevicesPage() {
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
    onSuccess: () => { setRenaming(null); done('Cihaz adı güncellendi.')(); },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (d) => api.call('devices_revoke_device', { params: { device_id: d.id } }),
    onSuccess: () => { setRevoking(null); done('Cihazın erişimi kaldırıldı; yayınları ve oturumu sonlandırıldı.')(); },
    onError,
  });

  if (devices.isLoading) return <Spinner fullScreen />;
  return (
    <Page title="Cihazlar" subtitle="Hesabınıza erişen cihazlar. Tanımadığınız bir cihazın erişimini kaldırın.">
      {!devices.data?.length ? (
        <EmptyState icon={Monitor} title="Kayıtlı cihaz yok" />
      ) : (
        <ul className={styles.list}>
          {devices.data.map((d) => {
            const Icon = ICON[d.device_type] ?? Monitor;
            return (
              <li key={d.id} className={`${styles.item} ${d.is_current ? styles.current : ''}`}>
                <Icon size={28} aria-hidden="true" className={styles.icon} />
                <div className={styles.body}>
                  <strong>
                    {d.name} {d.is_current && <span className={styles.badge}>Bu cihaz</span>}
                    {d.is_trusted && <span className={styles.trusted}>Güvenilir</span>}
                  </strong>
                  <small>
                    {[d.browser, d.os].filter(Boolean).join(' · ')} · Son görülme {when(d.last_seen_at)}
                    {d.last_ip ? ` · ${d.last_ip}` : ''} · {d.login_count} giriş
                  </small>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setRenaming({ id: d.id, name: d.name })} aria-label="Yeniden adlandır"><Pencil size={16} /></Button>
                <Button variant="ghost" size="sm" onClick={() => trust.mutate(d)} aria-label={d.is_trusted ? 'Güveni kaldır' : 'Güvenilir yap'}>
                  {d.is_trusted ? <ShieldOff size={16} /> : <ShieldCheck size={16} />}
                </Button>
                {!d.is_current && (
                  <Button variant="ghost" size="sm" onClick={() => setRevoking(d)} aria-label="Erişimi kaldır"><Trash2 size={16} /></Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <Modal isOpen={Boolean(renaming)} onClose={() => setRenaming(null)} title="Cihazı yeniden adlandır">
        <form onSubmit={(e) => { e.preventDefault(); rename.mutate(renaming); }} style={{ display: 'grid', gap: '0.75rem' }}>
          <input className="input-field" maxLength={100} value={renaming?.name ?? ''} onChange={(e) => setRenaming((r) => ({ ...r, name: e.target.value }))} aria-label="Cihaz adı" autoFocus />
          <Button type="submit" disabled={!renaming?.name?.trim() || rename.isPending}>Kaydet</Button>
        </form>
      </Modal>
      <Modal isOpen={Boolean(revoking)} onClose={() => setRevoking(null)} title="Erişimi kaldır">
        <p>{revoking?.name} cihazının oturumu ve açık yayınları sonlandırılacak. Devam edilsin mi?</p>
        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={() => setRevoking(null)}>Vazgeç</Button>
          <Button variant="danger" onClick={() => revoke.mutate(revoking)} disabled={revoke.isPending}>Erişimi kaldır</Button>
        </div>
      </Modal>
    </Page>
  );
}
