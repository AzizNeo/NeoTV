import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Modal } from '@/shared/components/Modal/Modal';
import { Page } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { Avatar } from '../components/Avatar';
import { AVATARS } from '../avatars';
import { profileKeys, useProfile } from '../components/ProfileProvider';
import styles from './Profiles.module.css';
import { useT } from '../i18n';

function ProfileForm({ initial, onSubmit, submitting }) {
  const t = useT();
  const [name, setName] = useState(initial?.name ?? '');
  const [avatar, setAvatar] = useState(initial?.avatar ?? 'default');
  const [isKids, setIsKids] = useState(initial?.is_kids ?? false);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name: name.trim(), avatar, is_kids: isKids });
      }}
      style={{ display: 'grid', gap: '1rem' }}
    >
      <input className="input-field" placeholder={t('form.name')} maxLength={40} value={name} onChange={(e) => setName(e.target.value)} aria-label={t('form.name')} autoFocus />
      <div className={styles.avatarPicker} role="group" aria-label={t('form.avatar')}>
        {AVATARS.map((a) => (
          <button type="button" key={a} aria-pressed={a === avatar} onClick={() => setAvatar(a)} aria-label={a}>
            <Avatar avatar={a} size={56} />
          </button>
        ))}
      </div>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input type="checkbox" checked={isKids} onChange={(e) => setIsKids(e.target.checked)} /> {t('form.kids')}
      </label>
      <Button type="submit" disabled={!name.trim() || submitting}>{t('form.save')}</Button>
    </form>
  );
}

function PinForm({ profile, onDone }) {
  const t = useT();
  const toast = useToast();
  const [pin, setPin] = useState('');
  const [current, setCurrent] = useState('');
  const save = useMutation({
    mutationFn: () => api.call('profile_set_pin', { params: { profile_id: profile.id }, body: { pin, current_pin: current || null } }),
    onSuccess: () => { toast.success(t('pinForm.saved')); onDone(); },
    onError: (err) => toast.error(err.userMessage),
  });
  const clear = useMutation({
    mutationFn: () => api.call('profile_clear_pin', { params: { profile_id: profile.id }, body: { current_pin: current || null } }),
    onSuccess: () => { toast.success(t('pinForm.cleared')); onDone(); },
    onError: (err) => toast.error(err.userMessage),
  });
  const digits = (v) => v.replace(/\D/g, '').slice(0, 8);
  return (
    <div style={{ display: 'grid', gap: '0.75rem' }}>
      {profile.has_pin && <input className="input-field" placeholder={t('pinForm.current')} inputMode="numeric" value={current} onChange={(e) => setCurrent(digits(e.target.value))} aria-label={t('pinForm.current')} />}
      <input className="input-field" placeholder={t('pinForm.next')} inputMode="numeric" value={pin} onChange={(e) => setPin(digits(e.target.value))} aria-label={t('pinForm.nextLabel')} />
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <Button onClick={() => save.mutate()} disabled={pin.length < 4 || save.isPending}>{t('pinForm.set')}</Button>
        {profile.has_pin && <Button variant="secondary" onClick={() => clear.mutate()} disabled={clear.isPending}>{t('pinForm.clear')}</Button>}
      </div>
    </div>
  );
}

export default function ProfileManagePage() {
  const t = useT();
  const { profiles } = useProfile();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(null); // profile | 'new'
  const [pinFor, setPinFor] = useState(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: profileKeys.list });

  const upsert = useMutation({
    mutationFn: (values) =>
      editing === 'new'
        ? api.call('profile_create_profile', { body: values })
        : api.call('profile_update_profile', { params: { profile_id: editing.id }, body: values }),
    onSuccess: () => { setEditing(null); refresh(); },
    onError: (err) => toast.error(err.userMessage),
  });
  const remove = useMutation({
    mutationFn: (profile) => api.call('profile_delete_profile', { params: { profile_id: profile.id } }),
    onSuccess: () => { toast.success(t('removed')); refresh(); },
    onError: (err) => toast.error(err.userMessage),
  });

  return (
    <Page title={t('manage')} width="narrow" actions={<Button onClick={() => setEditing('new')}><Plus size={16} style={{ marginRight: 6 }} />{t('add')}</Button>}>
      <div className={styles.list}>
        {profiles.map((p) => (
          <div key={p.id} className={styles.row}>
            <Avatar avatar={p.avatar} size={56} locked={p.has_pin} />
            <div className={styles.rowBody}>
              <strong>{p.name}</strong>
              <small>{[p.is_default && t('main'), p.is_kids && t('kids'), p.has_pin && t('locked')].filter(Boolean).join(' · ')}</small>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setEditing(p)} aria-label={t('edit', { name: p.name })}><Pencil size={16} /></Button>
            <Button variant="ghost" size="sm" onClick={() => setPinFor(p)} aria-label={t('pinFor', { name: p.name })}><KeyRound size={16} /></Button>
            {!p.is_default && (
              <Button variant="ghost" size="sm" onClick={() => remove.mutate(p)} aria-label={t('remove', { name: p.name })}><Trash2 size={16} /></Button>
            )}
          </div>
        ))}
      </div>
      <Modal isOpen={Boolean(editing)} onClose={() => setEditing(null)} title={t(editing === 'new' ? 'newProfile' : 'editProfile')}>
        {editing && <ProfileForm initial={editing === 'new' ? null : editing} onSubmit={(v) => upsert.mutate(v)} submitting={upsert.isPending} />}
      </Modal>
      <Modal isOpen={Boolean(pinFor)} onClose={() => setPinFor(null)} title={t('pinTitle', { name: pinFor?.name ?? '' })}>
        {pinFor && <PinForm profile={pinFor} onDone={() => { setPinFor(null); refresh(); }} />}
      </Modal>
    </Page>
  );
}
