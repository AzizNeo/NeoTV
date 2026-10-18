import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Plus, Trash2, Tv } from 'lucide-react';
import { api } from '@/core/api/client';
import { useFormat } from '@/core/i18n';
import { useProfile } from '@/features/profiles';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Modal } from '@/shared/components/Modal/Modal';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useToast } from '@/shared/components/Toast/Toast';
import { useT } from '../i18n';
import { signInDetails } from '../signIn';
import styles from './TvAppsPage.module.css';

const KEY = ['xtream', 'credentials'];

export default function TvAppsPage() {
  const t = useT();
  const { current, profiles } = useProfile();
  if (current?.is_kids) {
    return (
      <Page title={t('title')} subtitle={t('subtitle')}>
        <EmptyState icon={Tv} title={t('kidsTitle')}>{t('kidsBody')}</EmptyState>
      </Page>
    );
  }
  return <Manager current={current} profiles={profiles} />;
}

function Manager({ current, profiles }) {
  const t = useT();
  const { dateTime } = useFormat();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [issued, setIssued] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const credentials = useQuery({ queryKey: KEY, queryFn: () => api.call('xtream_list_credentials') });
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY });
  const onError = (err) => toast.error(err.userMessage);

  const issue = useMutation({
    mutationFn: (body) => api.call('xtream_issue_credential', { body }),
    onSuccess: (result) => {
      setAdding(false);
      setIssued(result); // the password lives only in this state, until the dialog closes
      refresh();
    },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (c) => api.call('xtream_revoke_credential', { params: { credential_id: c.id } }),
    onSuccess: () => {
      setRevoking(null);
      toast.success(t('revoked'));
      refresh();
    },
    onError,
  });

  if (credentials.isLoading) return <Spinner fullScreen />;
  const items = credentials.data ?? [];
  return (
    <Page
      title={t('title')}
      subtitle={t('subtitle')}
      actions={<Button onClick={() => setAdding(true)}><Plus size={16} aria-hidden="true" /> {t('add')}</Button>}
    >
      <p className={styles.notice}>{t('notice')}</p>
      {!items.length ? (
        <EmptyState icon={Tv} title={t('empty')}>{t('emptyBody')}</EmptyState>
      ) : (
        <ul className={styles.list}>
          {items.map((c) => (
            <li key={c.id} className={styles.item}>
              <Tv size={28} aria-hidden="true" className={styles.icon} />
              <div className={styles.body}>
                <strong>{c.label}</strong>
                <small>
                  {t('username')}: <span className={styles.mono}>{c.username}</span>
                  {' · '}
                  {c.profile_name ? `${t('profile')}: ${c.profile_name}` : <span className={styles.warn}>{t('profileGone')}</span>}
                </small>
                <small>
                  {t('created', { when: dateTime(c.created_at) })}
                  {' · '}
                  {c.last_used_at ? t('lastUsed', { when: dateTime(c.last_used_at) }) : t('neverUsed')}
                </small>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setRevoking(c)} aria-label={`${t('revoke')}: ${c.label}`}>
                <Trash2 size={16} aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <AddDialog
          current={current}
          profiles={profiles}
          pending={issue.isPending}
          onSubmit={(body) => issue.mutate(body)}
          onClose={() => setAdding(false)}
        />
      )}
      <Modal isOpen={Boolean(issued)} onClose={() => setIssued(null)} title={t('issuedTitle')}>
        {issued && <Issued issued={issued} onDone={() => setIssued(null)} />}
      </Modal>
      <Modal isOpen={Boolean(revoking)} onClose={() => setRevoking(null)} title={t('revokeTitle')}>
        <p>{t('revokeBody', { label: revoking?.label ?? '' })}</p>
        <div className={styles.buttons}>
          <Button variant="secondary" onClick={() => setRevoking(null)}>{t('cancel')}</Button>
          <Button variant="danger" onClick={() => revoke.mutate(revoking)} disabled={revoke.isPending}>{t('revoke')}</Button>
        </div>
      </Modal>
    </Page>
  );
}

function AddDialog({ current, profiles, pending, onSubmit, onClose }) {
  const t = useT();
  // A PIN-protected profile can be bound only from a session where its PIN was entered (ADR-0011).
  const locked = (p) => p.has_pin && p.id !== current?.id;
  const [label, setLabel] = useState('');
  const [profileId, setProfileId] = useState(() => String((profiles.find((p) => p.id === current?.id) ?? profiles.find((p) => !locked(p)))?.id ?? ''));
  return (
    <Modal isOpen onClose={onClose} title={t('add')}>
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({ label: label.trim(), profile_id: Number(profileId) });
        }}
      >
        <label htmlFor="tv-app-label">{t('label')}</label>
        <input
          id="tv-app-label"
          className="input-field"
          maxLength={40}
          required
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          aria-describedby="tv-app-label-hint"
          autoFocus
        />
        <small id="tv-app-label-hint" className={styles.hint}>{t('labelHint')}</small>
        <label htmlFor="tv-app-profile">{t('profile')}</label>
        <select id="tv-app-profile" className="input-field" value={profileId} onChange={(e) => setProfileId(e.target.value)} required>
          {profiles.map((p) => (
            <option key={p.id} value={p.id} disabled={locked(p)}>
              {locked(p) ? t('pinLocked', { name: p.name }) : p.name}
            </option>
          ))}
        </select>
        <div className={styles.buttons}>
          <Button type="button" variant="secondary" onClick={onClose}>{t('cancel')}</Button>
          <Button type="submit" disabled={!label.trim() || !profileId || pending}>{t('create')}</Button>
        </div>
      </form>
    </Modal>
  );
}

function Issued({ issued, onDone }) {
  const t = useT();
  const toast = useToast();
  const copy = async (what, value) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t('copied', { what }));
    } catch {
      /* clipboard refused (permissions, insecure context): the value stays visible to copy by hand */
    }
  };
  return (
    <>
      <p role="alert" className={styles.once}>{t('issuedOnce')}</p>
      <dl className={styles.details}>
        {signInDetails(issued).map(([key, value]) => (
          <div key={key} className={styles.detail}>
            <dt>{t(key)}</dt>
            <dd>
              <code className={styles.mono}>{value}</code>
              <Button variant="ghost" size="sm" onClick={() => copy(t(key), value)} aria-label={t('copy', { what: t(key) })}>
                <Copy size={16} aria-hidden="true" />
              </Button>
            </dd>
          </div>
        ))}
      </dl>
      <p className={styles.hint}>{t('issuedFormat')}</p>
      <div className={styles.buttons}>
        <Button onClick={onDone}>{t('done')}</Button>
      </div>
    </>
  );
}
