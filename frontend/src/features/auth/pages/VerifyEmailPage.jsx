import { LinkActionPage } from '../components/LinkActionPage';

const refreshUser = ({ isAuthenticated, reloadUser }) => isAuthenticated && reloadUser().catch(() => {});

export default function VerifyEmailPage() {
  return (
    <LinkActionPage
      operationId="identity_verify_email"
      title="E-posta doğrulama"
      successText="E-posta adresiniz doğrulandı."
      errorHint="Hesap sayfanızdan yeni bir doğrulama bağlantısı isteyebilirsiniz."
      onDone={refreshUser}
    />
  );
}
