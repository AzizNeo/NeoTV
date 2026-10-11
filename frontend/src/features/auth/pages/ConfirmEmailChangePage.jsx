import { LinkActionPage } from '../components/LinkActionPage';

const refreshUser = ({ isAuthenticated, reloadUser }) => isAuthenticated && reloadUser().catch(() => {});

export default function ConfirmEmailChangePage() {
  return (
    <LinkActionPage
      operationId="identity_confirm_email_change"
      title="Yeni e-posta adresi"
      successText="E-posta adresiniz değiştirildi ve doğrulandı."
      errorHint="Hesap sayfanızdan değişikliği yeniden isteyebilirsiniz."
      onDone={refreshUser}
    />
  );
}
