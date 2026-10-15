import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, ExternalLink, RefreshCw, Search, Unlink } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Modal } from '@/shared/components/Modal/Modal';
import { Panel } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { Badge, DataTable } from '../components/DataTable';
import { when } from '../format';
import { useAdminMutation } from '../hooks/useAdminMutation';
import styles from '../components/Admin.module.css';
import { useT } from '../i18n';
import { slugify, tmdbPage } from './tmdb';

/**
 * TMDB importer: search TMDB, import a hit into a title (new → draft, existing → enriched
 * without touching its editorial fields), refresh or forget links. Every write goes through
 * the backend's `tmdb` module, which writes through titles' own admin use case.
 */
const ROOT = ['admin', 'tmdb'];
const LINKS = [...ROOT, 'links'];
const TITLES = ['admin', 'titles'];

export default function TmdbSection() {
  const t = useT();
  const status = useQuery({ queryKey: [...ROOT, 'status'], queryFn: () => api.call('tmdb_status') });
  const configured = status.data?.configured;
  const links = useQuery({ queryKey: LINKS, queryFn: () => api.call('tmdb_links'), enabled: Boolean(status.data) });

  const [form, setForm] = useState({ query: '', kind: 'movie', year: '' });
  const [asked, setAsked] = useState(null); // the submitted search (the query runs only on submit)
  const hits = useQuery({
    queryKey: [...ROOT, 'search', asked],
    queryFn: () => api.call('tmdb_search', { query: { query: asked.query, kind: asked.kind, year: asked.year || undefined } }),
    enabled: Boolean(asked && configured),
    staleTime: 5 * 60_000,
  });

  const [target, setTarget] = useState(null); // { hit, slug, play_ref }
  const existing = useQuery({
    queryKey: [...TITLES, 'pick', target?.slug],
    queryFn: () => api.call('titles_admin_list', { query: { search: target.slug || undefined, limit: 20 } }),
    enabled: Boolean(target),
    placeholderData: (previous) => previous,
  });
  const match = existing.data?.items.find((x) => x.slug === target?.slug);

  const link = useAdminMutation(
    ({ hit, slug, play_ref }) => api.call('tmdb_link', {
      params: { slug },
      body: { tmdb_id: hit.tmdb_id, kind: hit.kind, play_ref: hit.kind === 'movie' && play_ref ? play_ref : undefined },
    }),
    {
      invalidate: [LINKS, TITLES],
      success: (r) => t(r.created ? 'tmdb.created' : 'tmdb.updated', { slug: r.slug }),
      onSuccess: () => setTarget(null),
    },
  );
  const refresh = useAdminMutation((l) => api.call('tmdb_refresh', { params: { slug: l.slug } }), {
    invalidate: [LINKS, TITLES], success: (r) => t('tmdb.refreshed', { slug: r.slug }),
  });
  const unlink = useAdminMutation((l) => api.call('tmdb_unlink', { params: { slug: l.slug } }), {
    invalidate: [LINKS], success: t('tmdb.unlinked'),
  });

  if (status.isLoading) return <Spinner />;
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  return (
    <>
      {!configured && (
        <Panel title={t('tmdb.notConfiguredTitle')}>
          <p>{t('tmdb.notConfigured')}</p>
          <p className={styles.mono}>TMDB_READ_TOKEN=…</p>
        </Panel>
      )}

      {configured && (
        <Panel title={t('tmdb.search')}>
          <form className={styles.searchRow} role="search" onSubmit={(e) => { e.preventDefault(); if (form.query.trim()) setAsked({ ...form, query: form.query.trim() }); }}>
            <select className="input-field" aria-label={t('tmdb.kind')} value={form.kind} onChange={set('kind')}>
              <option value="movie">{t('tmdb.movie')}</option>
              <option value="series">{t('tmdb.series')}</option>
            </select>
            <input className="input-field" type="search" required maxLength={100} placeholder={t('tmdb.query')} aria-label={t('tmdb.query')} value={form.query} onChange={set('query')} />
            <input className="input-field" type="number" min={1888} max={2100} placeholder={t('tmdb.year')} aria-label={t('tmdb.year')} value={form.year} onChange={set('year')} />
            <Button type="submit" size="sm" disabled={hits.isFetching}><Search size={16} /> {t('tmdb.find')}</Button>
          </form>
          {hits.isFetching && <Spinner />}
          {hits.data && !hits.isFetching && (hits.data.length ? (
            <ul className={styles.hits}>
              {hits.data.map((hit) => (
                <li key={hit.tmdb_id} className={styles.hit}>
                  {hit.poster_url
                    ? <img src={hit.poster_url} alt="" loading="lazy" width={92} height={138} />
                    : <div className={styles.noPoster} aria-hidden="true" />}
                  <div>
                    <strong>{hit.name}</strong> {hit.year && <span className={styles.muted}>({hit.year})</span>}
                    {hit.original_name && hit.original_name !== hit.name && <div className={styles.muted}>{hit.original_name}</div>}
                    {hit.overview && <p className={styles.overview}>{hit.overview}</p>}
                    <div className={styles.actionsStart}>
                      <Button size="sm" onClick={() => setTarget({ hit, slug: slugify(hit.original_name || hit.name), play_ref: '' })}>
                        <Download size={16} /> {t('tmdb.import')}
                      </Button>
                      <a href={tmdbPage(hit)} target="_blank" rel="noopener noreferrer" className={styles.muted}>
                        TMDB {hit.tmdb_id} <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : <EmptyState title={t('tmdb.noHits')} />)}
        </Panel>
      )}

      <Panel title={t('tmdb.links')}>
        <DataTable
          rowKey="slug"
          loading={links.isLoading}
          rows={links.data}
          empty={t('tmdb.noLinks')}
          columns={[
            { key: 'slug', label: t('col.title'), render: (l) => <Link to={`/title/${l.slug}`}>{l.slug}</Link> },
            { key: 'kind', label: t('col.kind'), render: (l) => t(l.kind === 'movie' ? 'tmdb.movie' : 'tmdb.series') },
            { key: 'tmdb_id', label: 'TMDB', render: (l) => <a href={tmdbPage(l)} target="_blank" rel="noopener noreferrer" className={styles.mono}>{l.tmdb_id}</a> },
            { key: 'synced_at', label: t('col.lastSync'), render: (l) => when(l.synced_at) },
          ]}
          actions={(l) => (
            <>
              {configured && <Button size="sm" variant="ghost" aria-label={t('tmdb.refresh')} disabled={refresh.isPending} onClick={() => refresh.mutate(l)}><RefreshCw size={16} /></Button>}
              <Button size="sm" variant="ghost" aria-label={t('tmdb.unlink')} onClick={() => unlink.mutate(l)}><Unlink size={16} /></Button>
            </>
          )}
        />
      </Panel>

      <p className={styles.muted}>
        {t('tmdb.attribution')} <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer">themoviedb.org</a>
      </p>

      <Modal isOpen={Boolean(target)} onClose={() => setTarget(null)} title={t('tmdb.importTitle', { name: target?.hit.name ?? '' })}>
        {target && (
          <form className={styles.form} onSubmit={(e) => { e.preventDefault(); link.mutate(target); }}>
            <label className={styles.field}>
              <span>{t('tmdb.slug')}</span>
              <input
                className="input-field" required maxLength={80} pattern="[a-z0-9]+(-[a-z0-9]+)*" list="tmdb-titles"
                value={target.slug} onChange={(e) => setTarget((x) => ({ ...x, slug: e.target.value.trim().toLowerCase() }))}
              />
              <datalist id="tmdb-titles">
                {existing.data?.items.map((x) => <option key={x.slug} value={x.slug}>{x.name}</option>)}
              </datalist>
            </label>
            <p>
              {match
                ? <><Badge ok>{t('tmdb.existing')}</Badge> {t('tmdb.existingHint', { name: match.name })}</>
                : <><Badge>{t('tmdb.new')}</Badge> {t(target.hit.kind === 'movie' ? 'tmdb.newMovieHint' : 'tmdb.newSeriesHint')}</>}
            </p>
            {!match && target.hit.kind === 'movie' && (
              <label className={styles.field}>
                <span>{t('tmdb.playRef')}</span>
                <input className="input-field" maxLength={64} placeholder="vod:…" value={target.play_ref} onChange={(e) => setTarget((x) => ({ ...x, play_ref: e.target.value.trim() }))} />
              </label>
            )}
            <Button type="submit" disabled={link.isPending}>{t(match ? 'tmdb.enrich' : 'tmdb.create')}</Button>
          </form>
        )}
      </Modal>
    </>
  );
}
