import PropTypes from 'prop-types';
import { useLocale } from './locale';

/**
 * Compact language picker for screens without the account menu (sign-in, sign-up, e-mail links).
 * Each option is labelled in its own language — a viewer who cannot read the current one still
 * finds theirs.
 */
export function LanguageSwitch({ className }) {
  const { locale, setLocale, locales } = useLocale();
  return (
    <div className={className} role="group" aria-label="Dil / Language">
      {Object.entries(locales).map(([id, name]) => (
        <button key={id} type="button" lang={id} aria-pressed={locale === id} onClick={() => setLocale(id)}>
          {name}
        </button>
      ))}
    </div>
  );
}
LanguageSwitch.propTypes = { className: PropTypes.string };
