import { LinkActionPage } from '../components/LinkActionPage';
import { useT } from '../i18n';

const refreshUser = ({ isAuthenticated, reloadUser }) => isAuthenticated && reloadUser().catch(() => {});

export default function ConfirmEmailChangePage() {
  const t = useT();
  return (
    <LinkActionPage
      operationId="identity_confirm_email_change"
      title={t('link.confirm.title')}
      successText={t('link.confirm.done')}
      errorHint={t('link.confirm.hint')}
      onDone={refreshUser}
    />
  );
}
