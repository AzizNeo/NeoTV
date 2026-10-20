import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Archive, KeyRound, Plus, Trash2 } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Modal } from '@/shared/components/Modal/Modal';
import { Badge, DataTable } from '../components/DataTable';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

const KEY = ['admin', 'live', 'channels'];
const ARCHIVE_DAYS = [0, 1, 3, 7]; // the server caps at ARCHIVE_MAX_DAYS (7)
const EMPTY = { name: '', source_type: 'external', upstream_url: '', delivery: 'proxy', rating: 'unrated' };

export default function LiveSection() {
  const t = useT();
  const [form, setForm] = useState(null);
  const [secret, setSecret] = useState(null); // ingest key is shown exactly once
  const [archiving, setArchiving] = useState(null); // { channel, days, rights }
  const channels = useQuery({ queryKey: KEY, queryFn: () => api.call('live_admin_list') });
  const create = useAdminMutation(
    (body) => api.call('live_admin_create', { body: { ...body, upstream_url: body.source_type === 'external' ? body.upstream_url : null } }),
    { invalidate: [KEY], success: t('live.created'), onSuccess: (r) => { setForm(null); if (r.ingest_key) setSecret(r.ingest_key); } },
  );
  const rotate = useAdminMutation((c) => api.call('live_admin_rotate', { params: { channel_id: c.id } }), {
    invalidate: [KEY], onSuccess: (r) => setSecret(r.ingest_key),
  });
  const toggle = useAdminMutation((c) => api.call('live_admin_update', { params: { channel_id: c.id }, body: { is_active: !c.is_active } }), { invalidate: [KEY] });
  const remove = useAdminMutation((c) => api.call('live_admin_delete', { params: { channel_id: c.id } }), { invalidate: [KEY], success: t('live.deleted') });
  const setArchive = useAdminMutation(
    ({ channel, days, rights }) =>
      api.call('live_admin_set_archive', { params: { channel_id: channel.id }, body: { days, rights_confirmed: rights } }),
    { invalidate: [KEY], success: t('live.archiveSaved'), onSuccess: () => setArchiving(null) },
  );
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const needsRights = archiving && archiving.channel.source_type === 'external' && archiving.days > 0;

  return (
    <>
      <div className={styles.toolbar}><Button size="sm" onClick={() => setForm(EMPTY)}><Plus size={16} /> {t('live.add')}</Button></div>
      <DataTable
        loading={channels.isLoading}
        rows={channels.data}
        columns={[
          { key: 'name', label: t('col.name') },
          { key: 'source_type', label: t('col.source') },
          { key: 'delivery', label: t('col.delivery') },
          { key: 'ingest_key_last4', label: t('col.key'), render: (c) => (c.ingest_key_last4 ? <span className={styles.mono}>••••{c.ingest_key_last4}</span> : '—') },
          { key: 'is_live', label: t('col.broadcast'), render: (c) => <Badge ok={c.is_live}>{t(c.is_live ? 'live.live' : 'live.offAir')}</Badge> },
          { key: 'is_active', label: t('col.status'), render: (c) => <Badge ok={c.is_active}>{t(c.is_active ? 'live.active' : 'live.inactive')}</Badge> },
          { key: 'archive_days', label: t('col.archive'), render: (c) => (c.archive_days ? t('live.archiveDays', { count: c.archive_days }) : '—') },
        ]}
        actions={(c) => (
          <>
            {c.source_type === 'ingest' && <Button size="sm" variant="ghost" aria-label={t('live.rotate')} onClick={() => rotate.mutate(c)}><KeyRound size={16} /></Button>}
            <Button size="sm" variant="ghost" aria-label={t('live.archive')} onClick={() => setArchiving({ channel: c, days: c.archive_days || 3, rights: false })}><Archive size={16} /></Button>
            <Button size="sm" variant="ghost" onClick={() => toggle.mutate(c)}>{t(c.is_active ? 'live.deactivate' : 'live.activate')}</Button>
            <Button size="sm" variant="ghost" aria-label={t('live.delete')} onClick={() => remove.mutate(c)}><Trash2 size={16} /></Button>
          </>
        )}
      />
      <Modal isOpen={Boolean(form)} onClose={() => setForm(null)} title={t('live.addTitle')}>
        {form && (
          <form className={styles.form} onSubmit={(e) => { e.preventDefault(); create.mutate(form); }}>
            <input className="input-field" required maxLength={100} placeholder={t('live.name')} aria-label={t('live.name')} value={form.name} onChange={set('name')} />
            <select className="input-field" aria-label={t('live.sourceType')} value={form.source_type} onChange={set('source_type')}>
              <option value="external">{t('live.external')}</option>
              <option value="ingest">{t('live.ingest')}</option>
            </select>
            {form.source_type === 'external' && (
              <input className="input-field" type="url" required placeholder="https://…/index.m3u8" aria-label={t('live.sourceUrl')} value={form.upstream_url} onChange={set('upstream_url')} />
            )}
            <select className="input-field" aria-label={t('live.delivery')} value={form.delivery} onChange={set('delivery')}>
              <option value="proxy">{t('live.proxy')}</option>
              <option value="direct">{t('live.direct')}</option>
            </select>
            <select className="input-field" aria-label={t('live.rating')} value={form.rating} onChange={set('rating')}>
              {['general', 'teen', 'adult', 'unrated'].map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <Button type="submit" disabled={create.isPending}>{t('live.create')}</Button>
          </form>
        )}
      </Modal>
      <Modal isOpen={Boolean(archiving)} onClose={() => setArchiving(null)} title={t('live.archiveTitle', { name: archiving?.channel.name ?? '' })}>
        {archiving && (
          <form className={styles.form} onSubmit={(e) => { e.preventDefault(); setArchive.mutate(archiving); }}>
            <p>{t('live.archiveHelp')}</p>
            <label htmlFor="archive-days">{t('live.archiveLength')}</label>
            <select id="archive-days" className="input-field" value={archiving.days} onChange={(e) => setArchiving((a) => ({ ...a, days: Number(e.target.value), rights: false }))}>
              {ARCHIVE_DAYS.map((d) => <option key={d} value={d}>{d ? t('live.archiveDays', { count: d }) : t('live.archiveOff')}</option>)}
            </select>
            {needsRights && (
              <label className={styles.check}>
                <input type="checkbox" checked={archiving.rights} onChange={(e) => setArchiving((a) => ({ ...a, rights: e.target.checked }))} />
                {t('live.archiveRights')}
              </label>
            )}
            <Button type="submit" disabled={setArchive.isPending || (needsRights && !archiving.rights)}>{t('live.save')}</Button>
          </form>
        )}
      </Modal>
      <Modal isOpen={Boolean(secret)} onClose={() => setSecret(null)} title={t('live.keyTitle')}>
        <p>{t('live.keyOnce')}</p>
        <p className={styles.mono} style={{ wordBreak: 'break-all' }}>{secret}</p>
        <Button onClick={() => { navigator.clipboard?.writeText(secret); setSecret(null); }}>{t('live.copy')}</Button>
      </Modal>
    </>
  );
}
