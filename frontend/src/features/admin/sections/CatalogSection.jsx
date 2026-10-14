import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Trash2, Upload } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Modal } from '@/shared/components/Modal/Modal';
import { Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { Badge, DataTable, Pager } from '../components/DataTable';
import { when } from '../format';
import { TaskProgress } from '../components/TaskProgress';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';

const PLAYLISTS = ['admin', 'catalog', 'playlists'];
const CHANNELS = ['admin', 'catalog', 'channels'];
const PER_PAGE = 50;

export default function CatalogSection() {
  const t = useT();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [importing, setImporting] = useState(false);
  const [task, setTask] = useState(null);

  const playlists = useQuery({ queryKey: PLAYLISTS, queryFn: () => api.call('catalog_admin_playlists') });
  const channels = useQuery({
    queryKey: [...CHANNELS, page, search],
    queryFn: () => api.call('catalog_admin_list', { query: { page, per_page: PER_PAGE, search: search || undefined, include_inactive: true } }),
    placeholderData: (previous) => previous,
  });
  const sync = useAdminMutation((p) => api.call('catalog_admin_sync', { params: { playlist_id: p.id } }), { onSuccess: (r) => setTask(r.task_id) });
  const runImport = useAdminMutation((body) => api.call('catalog_admin_import', { body }), {
    onSuccess: (r) => { setImporting(false); setTask(r.task_id); },
  });
  const removePlaylist = useAdminMutation((p) => api.call('catalog_admin_delete_playlist', { params: { playlist_id: p.id } }), {
    invalidate: [PLAYLISTS, CHANNELS], success: t('catalog.playlistDeleted'),
  });
  const remove = useAdminMutation((c) => api.call('catalog_admin_delete', { params: { channel_id: c.id } }), {
    invalidate: [CHANNELS, PLAYLISTS], success: t('catalog.channelRemoved'),
  });

  const onTaskDone = (status) => {
    setTask(null);
    if (status.state === 'SUCCESS') toast.success(t('catalog.updated'));
    else toast.error(status.error ?? t('catalog.taskFailed'));
    queryClient.invalidateQueries({ queryKey: ['admin', 'catalog'] });
  };

  return (
    <>
      <Panel title={t('catalog.playlists')} actions={<Button size="sm" onClick={() => setImporting(true)}><Upload size={16} /> {t('catalog.import')}</Button>}>
        {task && <TaskProgress taskId={task} onDone={onTaskDone} />}
        <DataTable
          loading={playlists.isLoading}
          rows={playlists.data}
          columns={[
            { key: 'name', label: t('col.name') },
            { key: 'channel_count', label: t('col.channels') },
            { key: 'last_synced_at', label: t('col.lastSync'), render: (p) => when(p.last_synced_at) },
            { key: 'last_sync_status', label: t('col.status'), render: (p) => p.last_sync_status ? <Badge ok={p.last_sync_status === 'ok'}>{p.last_sync_status}</Badge> : '—' },
            { key: 'last_sync_error', label: t('col.error') },
          ]}
          actions={(p) => (
            <>
              {p.has_source && <Button size="sm" variant="ghost" aria-label={t('catalog.sync')} disabled={Boolean(task)} onClick={() => sync.mutate(p)}><RefreshCw size={16} /></Button>}
              {!p.is_system && <Button size="sm" variant="ghost" aria-label={t('catalog.delete')} onClick={() => removePlaylist.mutate(p)}><Trash2 size={16} /></Button>}
            </>
          )}
        />
      </Panel>
      <Panel title={t('catalog.channels')}>
        <div className={styles.toolbar}>
          <input className="input-field" type="search" placeholder={t('catalog.search')} aria-label={t('catalog.searchLabel')} value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        </div>
        <DataTable
          loading={channels.isLoading}
          rows={channels.data?.items}
          columns={[
            { key: 'name', label: t('col.name') },
            { key: 'group', label: t('col.group') },
            { key: 'kind', label: t('col.kind') },
            { key: 'delivery', label: t('col.delivery') },
            { key: 'is_active', label: t('col.status'), render: (c) => <Badge ok={c.is_active}>{t(c.is_active ? 'catalog.onAir' : 'catalog.hidden')}</Badge> },
          ]}
          actions={(c) => (c.is_active ? (
            <Button size="sm" variant="ghost" aria-label={t('catalog.remove')} onClick={() => remove.mutate(c)}><Trash2 size={16} /></Button>
          ) : null)}
        />
        {channels.data && <Pager page={page} perPage={PER_PAGE} total={channels.data.total} onPage={setPage} />}
      </Panel>
      <ImportModal open={importing} onClose={() => setImporting(false)} onSubmit={(body) => runImport.mutate(body)} busy={runImport.isPending} />
    </>
  );
}

function ImportModal({ open, onClose, onSubmit, busy }) {
  const t = useT();
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const valid = Boolean(url.trim()) !== Boolean(text.trim()); // exactly one source
  return (
    <Modal isOpen={open} onClose={onClose} title={t('catalog.import')}>
      <form className={styles.form} onSubmit={(e) => { e.preventDefault(); onSubmit(url.trim() ? { url: url.trim() } : { text }); }}>
        <input className="input-field" type="url" placeholder={t('catalog.url')} aria-label={t('catalog.urlLabel')} value={url} onChange={(e) => setUrl(e.target.value)} />
        <textarea className="input-field" rows={6} placeholder={t('catalog.paste')} aria-label={t('catalog.pasteLabel')} value={text} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" disabled={!valid || busy}>{t('catalog.run')}</Button>
      </form>
    </Modal>
  );
}
