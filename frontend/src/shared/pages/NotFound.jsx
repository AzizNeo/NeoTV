import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';

export default function NotFound() {
  return (
    <EmptyState icon={Compass} title="Sayfa bulunamadı" action={<Link to="/">Ana sayfaya dön</Link>}>
      Aradığınız sayfa taşınmış ya da hiç var olmamış olabilir.
    </EmptyState>
  );
}
