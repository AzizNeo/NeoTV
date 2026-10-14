import { LinkActionPage } from '../components/LinkActionPage';
import { useT } from '../i18n';

const refreshUser = ({ isAuthenticated, reloadUser }) => isAuthenticated && reloadUser().catch(() => {});

export default function VerifyEmailPage() {
  const t = useT();
  return (
    <LinkActionPage
      operationId="identity_verify_email"
      title={t('link.verify.title')}
      successText={t('link.verify.done')}
      errorHint={t('link.verify.hint')}
      onDone={refreshUser}
    />
  );
}
