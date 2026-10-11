import { LinkActionPage } from '../components/LinkActionPage';

// The server ended every session (a takeover is assumed): forget the local one too.
const dropSession = ({ forgetSession }) => forgetSession();

export default function RevertEmailChangePage() {
  return (
    <LinkActionPage
      operationId="identity_revert_email_change"
      title="E-posta değişikliğini geri al"
      successText="E-posta adresiniz geri alındı ve tüm oturumlar kapatıldı. Bu adrese gönderdiğimiz bağlantıyla yeni bir şifre belirleyin."
      errorHint="Sorun sürerse yöneticiye başvurun."
      onDone={dropSession}
    />
  );
}
