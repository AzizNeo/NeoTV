import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Heart } from 'lucide-react';
import { useToast } from '@/shared/components/Toast/Toast';
import { getFavoriteRefs, libraryKeys, setFavorite } from '../api';
import styles from './FavoriteToggle.module.css';
import { useT } from '../i18n';

/** Contributed to `content.actions`: a heart on every playable card, wherever it is rendered. */
export function FavoriteToggle({ item }) {
  const t = useT();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: refs } = useQuery({ queryKey: libraryKeys.favoriteRefs, queryFn: getFavoriteRefs, staleTime: 60_000 });
  const isFavorite = refs?.includes(item.ref) ?? false;

  const toggle = useMutation({
    mutationFn: (on) => setFavorite(item.ref, on),
    onMutate: async (on) => {
      await queryClient.cancelQueries({ queryKey: libraryKeys.favoriteRefs });
      const previous = queryClient.getQueryData(libraryKeys.favoriteRefs);
      queryClient.setQueryData(libraryKeys.favoriteRefs, (list = []) => (on ? [item.ref, ...list] : list.filter((r) => r !== item.ref)));
      return { previous };
    },
    onError: (err, _on, ctx) => {
      queryClient.setQueryData(libraryKeys.favoriteRefs, ctx?.previous);
      toast.error(err.userMessage);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: libraryKeys.favorites }),
  });

  return (
    <button
      type="button"
      className={`${styles.heart} ${isFavorite ? styles.on : ''}`}
      aria-pressed={isFavorite}
      aria-label={t(isFavorite ? 'favorites.remove' : 'favorites.add', { title: item.title })}
      onClick={(e) => {
        e.stopPropagation();
        toggle.mutate(!isFavorite);
      }}
      disabled={toggle.isPending}
    >
      <Heart size={16} fill={isFavorite ? 'currentColor' : 'none'} />
    </button>
  );
}
