import { useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import styles from './Titles.module.css';

const typing = (el) => el?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el?.tagName);

/**
 * Contributed to `shell.actions`: opens search (the browse page) and focuses the field.
 * "/" does the same from anywhere — except while typing, where "/" is just a character.
 */
export function SearchAction() {
  const navigate = useNavigate();
  const location = useLocation();

  const open = useCallback(
    () =>
      navigate(
        // Already browsing? keep the current filters, just focus the field.
        { pathname: '/browse', search: location.pathname === '/browse' ? location.search : '' },
        { state: { focusSearch: Date.now() } },
      ),
    [navigate, location.pathname, location.search],
  );

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || typing(document.activeElement)) return;
      e.preventDefault();
      open();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <button
      type="button"
      className={styles.searchAction}
      aria-label="Ara"
      aria-keyshortcuts="/"
      title="Ara  ( / )"
      onClick={open}
    >
      <Search size={20} aria-hidden="true" />
    </button>
  );
}
