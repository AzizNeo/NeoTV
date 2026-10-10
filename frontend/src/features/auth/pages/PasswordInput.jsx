import { forwardRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import styles from './AuthLayout.module.css';

export const PasswordInput = forwardRef(function PasswordInput(props, ref) {
  const [visible, setVisible] = useState(false);
  return (
    <div className={styles.passwordBox}>
      <input ref={ref} type={visible ? 'text' : 'password'} className="input-field" {...props} />
      <button type="button" className={styles.eye} onClick={() => setVisible((v) => !v)} aria-label={visible ? 'Şifreyi gizle' : 'Şifreyi göster'}>
        {visible ? <EyeOff size={20} /> : <Eye size={20} />}
      </button>
    </div>
  );
});
