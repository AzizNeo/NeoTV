import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { useT } from './i18n';

export default function NotFound() {
  const t = useT();
  return (
    <EmptyState icon={Compass} title={t('notFound.title')} action={<Link to="/">{t('notFound.back')}</Link>}>
      {t('notFound.body')}
    </EmptyState>
  );
}
