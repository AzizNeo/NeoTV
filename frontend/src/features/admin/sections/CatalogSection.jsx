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

const PLAYLISTS = ['admin', 'catalog', 'playlists'];
const CHANNELS = ['admin', 'catalog', 'channels'];
const PER_PAGE = 50;

export default function CatalogSection() {
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
    invalidate: [PLAYLISTS, CHANNELS], success: 'Liste silindi.',
  });
  const remove = useAdminMutation((c) => api.call('catalog_admin_delete', { params: { channel_id: c.id } }), {
    invalidate: [CHANNELS, PLAYLISTS], success: 'Kanal katalogdan kaldırıldı.',
  });

  const onTaskDone = (status) => {
    setTask(null);
    if (status.state === 'SUCCESS') toast.success('Katalog güncellendi.');
    else toast.error(status.error ?? 'Görev başarısız oldu.');
    queryClient.invalidateQueries({ queryKey: ['admin', 'catalog'] });
  };

  return (
    <>
      <Panel title="Oynatma listeleri" actions={<Button size="sm" onClick={() => setImporting(true)}><Upload size={16} /> M3U içe aktar</Button>}>
        {task && <TaskProgress taskId={task} onDone={onTaskDone} />}
        <DataTable
          loading={playlists.isLoading}
          rows={playlists.data}
          columns={[
            { key: 'name', label: 'Ad' },
            { key: 'channel_count', label: 'Kanal' },
            { key: 'last_synced_at', label: 'Son eşitleme', render: (p) => when(p.last_synced_at) },
            { key: 'last_sync_status', label: 'Durum', render: (p) => p.last_sync_status ? <Badge ok={p.last_sync_status === 'ok'}>{p.last_sync_status}</Badge> : '—' },
            { key: 'last_sync_error', label: 'Hata' },
          ]}
          actions={(p) => (
            <>
              {p.has_source && <Button size="sm" variant="ghost" aria-label="Eşitle" disabled={Boolean(task)} onClick={() => sync.mutate(p)}><RefreshCw size={16} /></Button>}
              {!p.is_system && <Button size="sm" variant="ghost" aria-label="Sil" onClick={() => removePlaylist.mutate(p)}><Trash2 size={16} /></Button>}
            </>
          )}
        />
      </Panel>
      <Panel title="Kanallar">
        <div className={styles.toolbar}>
          <input className="input-field" type="search" placeholder="Kanal ara…" aria-label="Kanal ara" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        </div>
        <DataTable
          loading={channels.isLoading}
          rows={channels.data?.items}
          columns={[
            { key: 'name', label: 'Ad' },
            { key: 'group', label: 'Grup' },
            { key: 'kind', label: 'Tür' },
            { key: 'delivery', label: 'İletim' },
            { key: 'is_active', label: 'Durum', render: (c) => <Badge ok={c.is_active}>{c.is_active ? 'Yayında' : 'Gizli'}</Badge> },
          ]}
          actions={(c) => (c.is_active ? (
            <Button size="sm" variant="ghost" aria-label="Kaldır" onClick={() => remove.mutate(c)}><Trash2 size={16} /></Button>
          ) : null)}
        />
        {channels.data && <Pager page={page} perPage={PER_PAGE} total={channels.data.total} onPage={setPage} />}
      </Panel>
      <ImportModal open={importing} onClose={() => setImporting(false)} onSubmit={(body) => runImport.mutate(body)} busy={runImport.isPending} />
    </>
  );
}

function ImportModal({ open, onClose, onSubmit, busy }) {
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const valid = Boolean(url.trim()) !== Boolean(text.trim()); // exactly one source
  return (
    <Modal isOpen={open} onClose={onClose} title="M3U içe aktar">
      <form className={styles.form} onSubmit={(e) => { e.preventDefault(); onSubmit(url.trim() ? { url: url.trim() } : { text }); }}>
        <input className="input-field" type="url" placeholder="https://… (M3U adresi)" aria-label="M3U adresi" value={url} onChange={(e) => setUrl(e.target.value)} />
        <textarea className="input-field" rows={6} placeholder="…ya da M3U içeriğini yapıştırın" aria-label="M3U içeriği" value={text} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" disabled={!valid || busy}>İçe aktar</Button>
      </form>
    </Modal>
  );
}
