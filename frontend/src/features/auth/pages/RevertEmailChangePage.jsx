import { LinkActionPage } from '../components/LinkActionPage';
import { useT } from '../i18n';

// The server ended every session (a takeover is assumed): forget the local one too.
const dropSession = ({ forgetSession }) => forgetSession();

export default function RevertEmailChangePage() {
  const t = useT();
  return (
    <LinkActionPage
      operationId="identity_revert_email_change"
      title={t('link.revert.title')}
      successText={t('link.revert.done')}
      errorHint={t('link.revert.hint')}
      onDone={dropSession}
    />
  );
}
