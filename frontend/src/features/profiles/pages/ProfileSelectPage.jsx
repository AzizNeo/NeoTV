import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Settings2 } from 'lucide-react';
import { Modal } from '@/shared/components/Modal/Modal';
import { Button } from '@/shared/components/Button/Button';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { Avatar } from '../components/Avatar';
import { useProfile } from '../components/ProfileProvider';
import styles from './Profiles.module.css';
import { useT } from '../i18n';

export default function ProfileSelectPage() {
  const t = useT();
  const { profiles, isLoading, select } = useProfile();
  const navigate = useNavigate();
  const [pinFor, setPinFor] = useState(null);
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');

  const choose = async (profile, enteredPin) => {
    setError('');
    try {
      await select(profile.id, enteredPin);
      navigate('/', { replace: true });
    } catch (err) {
      if (err.code === 'PIN_REQUIRED') setPinFor(profile);
      else setError(err.userMessage);
    }
  };

  if (isLoading) return <Spinner fullScreen />;

  return (
    <main className={styles.screen}>
      <h1>{t('whoIsWatching')}</h1>
      {error && <p className="field-error" role="alert">{error}</p>}
      <ul className={styles.grid}>
        {profiles.map((p) => (
          <li key={p.id}>
            <button className={styles.tile} onClick={() => (p.has_pin ? setPinFor(p) : choose(p))}>
              <Avatar avatar={p.avatar} locked={p.has_pin} />
              <span>{p.name}</span>
              {p.is_kids && <span className={styles.kids}>{t('kids')}</span>}
            </button>
          </li>
        ))}
      </ul>
      <Link className={styles.manage} to="/profiles/manage">
        <Settings2 size={16} /> {t('manage')}
      </Link>
      <Modal isOpen={Boolean(pinFor)} onClose={() => { setPinFor(null); setPin(''); }} title={t('pinTitle', { name: pinFor?.name ?? '' })}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            choose(pinFor, pin).finally(() => setPin(''));
          }}
          style={{ display: 'grid', gap: '0.75rem' }}
        >
          <input className="input-field" inputMode="numeric" autoComplete="off" maxLength={8} autoFocus aria-label={t('pin')} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} />
          {error && <span className="field-error">{error}</span>}
          <Button type="submit" disabled={pin.length < 4}>{t('continue')}</Button>
        </form>
      </Modal>
    </main>
  );
}
