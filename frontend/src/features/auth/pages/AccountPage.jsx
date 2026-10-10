import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { LogOut, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/core/auth/AuthProvider';
import { Slot } from '@/core/featureKit';
import { Button } from '@/shared/components/Button/Button';
import { Page, Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { changePasswordSchema } from '../schema';
import { PasswordInput } from './PasswordInput';

export default function AccountPage() {
  const { user, changePassword, logoutEverywhere } = useAuth();
  const toast = useToast();
  const { register, handleSubmit, reset, formState } = useForm({ resolver: zodResolver(changePasswordSchema) });

  const onSubmit = async ({ current, next }) => {
    try {
      await changePassword(current, next);
      reset();
      toast.success('Şifreniz değiştirildi. Diğer cihazlardaki oturumlar kapatıldı.');
    } catch (err) {
      toast.error(err.userMessage);
    }
  };

  return (
    <Page title="Hesap" subtitle={`${user?.username}${user?.email ? ` · ${user.email}` : ''}`} width="narrow">
      {/* Other features add sections here (subscription summary, devices …). */}
      <Slot name="account.sections" />
      <Panel title="Şifre değiştir">
        <form onSubmit={handleSubmit(onSubmit)} style={{ display: 'grid', gap: '0.75rem' }} noValidate>
          <PasswordInput placeholder="Mevcut şifre" autoComplete="current-password" aria-label="Mevcut şifre" {...register('current')} />
          {formState.errors.current && <span className="field-error">{formState.errors.current.message}</span>}
          <PasswordInput placeholder="Yeni şifre" autoComplete="new-password" aria-label="Yeni şifre" {...register('next')} />
          {formState.errors.next && <span className="field-error">{formState.errors.next.message}</span>}
          <PasswordInput placeholder="Yeni şifre (tekrar)" autoComplete="new-password" aria-label="Yeni şifre tekrar" {...register('confirm')} />
          {formState.errors.confirm && <span className="field-error">{formState.errors.confirm.message}</span>}
          <div>
            <Button type="submit" disabled={formState.isSubmitting}>
              <ShieldCheck size={16} style={{ marginRight: 6 }} /> Şifreyi güncelle
            </Button>
          </div>
        </form>
      </Panel>
      <Panel title="Oturumlar">
        <p style={{ color: 'var(--color-text-secondary)', marginTop: 0 }}>
          Kaybolan bir cihaz veya paylaşılan bir şifreden şüpheleniyorsanız tüm cihazlarda oturumu kapatın.
        </p>
        <Button variant="danger" onClick={() => logoutEverywhere()}>
          <LogOut size={16} style={{ marginRight: 6 }} /> Tüm cihazlarda çıkış yap
        </Button>
      </Panel>
    </Page>
  );
}
