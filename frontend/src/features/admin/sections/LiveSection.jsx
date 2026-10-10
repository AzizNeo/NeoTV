import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { KeyRound, Plus, Trash2 } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Modal } from '@/shared/components/Modal/Modal';
import { Badge, DataTable } from '../components/DataTable';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';

const KEY = ['admin', 'live', 'channels'];
const EMPTY = { name: '', source_type: 'external', upstream_url: '', delivery: 'proxy', rating: 'unrated' };

export default function LiveSection() {
  const [form, setForm] = useState(null);
  const [secret, setSecret] = useState(null); // ingest key is shown exactly once
  const channels = useQuery({ queryKey: KEY, queryFn: () => api.call('live_admin_list') });
  const create = useAdminMutation(
    (body) => api.call('live_admin_create', { body: { ...body, upstream_url: body.source_type === 'external' ? body.upstream_url : null } }),
    { invalidate: [KEY], success: 'Kanal oluşturuldu.', onSuccess: (r) => { setForm(null); if (r.ingest_key) setSecret(r.ingest_key); } },
  );
  const rotate = useAdminMutation((c) => api.call('live_admin_rotate', { params: { channel_id: c.id } }), {
    invalidate: [KEY], onSuccess: (r) => setSecret(r.ingest_key),
  });
  const toggle = useAdminMutation((c) => api.call('live_admin_update', { params: { channel_id: c.id }, body: { is_active: !c.is_active } }), { invalidate: [KEY] });
  const remove = useAdminMutation((c) => api.call('live_admin_delete', { params: { channel_id: c.id } }), { invalidate: [KEY], success: 'Kanal silindi.' });
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  return (
    <>
      <div className={styles.toolbar}><Button size="sm" onClick={() => setForm(EMPTY)}><Plus size={16} /> Kanal ekle</Button></div>
      <DataTable
        loading={channels.isLoading}
        rows={channels.data}
        columns={[
          { key: 'name', label: 'Ad' },
          { key: 'source_type', label: 'Kaynak' },
          { key: 'delivery', label: 'İletim' },
          { key: 'ingest_key_last4', label: 'Anahtar', render: (c) => (c.ingest_key_last4 ? <span className={styles.mono}>••••{c.ingest_key_last4}</span> : '—') },
          { key: 'is_live', label: 'Yayın', render: (c) => <Badge ok={c.is_live}>{c.is_live ? 'Canlı' : 'Kapalı'}</Badge> },
          { key: 'is_active', label: 'Durum', render: (c) => <Badge ok={c.is_active}>{c.is_active ? 'Aktif' : 'Pasif'}</Badge> },
        ]}
        actions={(c) => (
          <>
            {c.source_type === 'ingest' && <Button size="sm" variant="ghost" aria-label="Anahtarı yenile" onClick={() => rotate.mutate(c)}><KeyRound size={16} /></Button>}
            <Button size="sm" variant="ghost" onClick={() => toggle.mutate(c)}>{c.is_active ? 'Pasifleştir' : 'Etkinleştir'}</Button>
            <Button size="sm" variant="ghost" aria-label="Sil" onClick={() => remove.mutate(c)}><Trash2 size={16} /></Button>
          </>
        )}
      />
      <Modal isOpen={Boolean(form)} onClose={() => setForm(null)} title="Canlı kanal ekle">
        {form && (
          <form className={styles.form} onSubmit={(e) => { e.preventDefault(); create.mutate(form); }}>
            <input className="input-field" required maxLength={100} placeholder="Kanal adı" aria-label="Kanal adı" value={form.name} onChange={set('name')} />
            <select className="input-field" aria-label="Kaynak türü" value={form.source_type} onChange={set('source_type')}>
              <option value="external">Harici kaynak (HLS URL)</option>
              <option value="ingest">RTMP yayın (OBS vb.)</option>
            </select>
            {form.source_type === 'external' && (
              <input className="input-field" type="url" required placeholder="https://…/index.m3u8" aria-label="Kaynak URL" value={form.upstream_url} onChange={set('upstream_url')} />
            )}
            <select className="input-field" aria-label="İletim" value={form.delivery} onChange={set('delivery')}>
              <option value="proxy">Proxy (imzalı)</option>
              <option value="direct">Doğrudan</option>
            </select>
            <select className="input-field" aria-label="Yaş sınırı" value={form.rating} onChange={set('rating')}>
              {['general', 'teen', 'adult', 'unrated'].map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <Button type="submit" disabled={create.isPending}>Oluştur</Button>
          </form>
        )}
      </Modal>
      <Modal isOpen={Boolean(secret)} onClose={() => setSecret(null)} title="Yayın anahtarı">
        <p>Bu anahtar yalnızca bir kez gösterilir. OBS'de “Stream Key” alanına girin.</p>
        <p className={styles.mono} style={{ wordBreak: 'break-all' }}>{secret}</p>
        <Button onClick={() => { navigator.clipboard?.writeText(secret); setSecret(null); }}>Kopyala ve kapat</Button>
      </Modal>
    </>
  );
}
