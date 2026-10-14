/**
 * Internationalisation (TR / EN). Features own their texts: `features/<id>/i18n.js` defines a
 * catalog with defineMessages and components read it with useTranslation. See messages.js.
 */
export { DEFAULT_LOCALE, LOCALES, UnknownLocaleError, getLocale, setLocale, subscribeLocale, useLocale } from './locale';
export { MessageCatalogError, defineMessages, labelOf, translate, useTranslation } from './messages';
export { errorMessages, messageFor } from './errors';
