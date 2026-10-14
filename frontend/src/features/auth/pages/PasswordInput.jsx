import { forwardRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import styles from './AuthLayout.module.css';
import { useT } from '../i18n';

export const PasswordInput = forwardRef(function PasswordInput(props, ref) {
  const t = useT();
  const [visible, setVisible] = useState(false);
  return (
    <div className={styles.passwordBox}>
      <input ref={ref} type={visible ? 'text' : 'password'} className="input-field" {...props} />
      <button type="button" className={styles.eye} onClick={() => setVisible((v) => !v)} aria-label={t(visible ? 'field.hide' : 'field.show')}>
        {visible ? <EyeOff size={20} /> : <Eye size={20} />}
      </button>
    </div>
  );
});
