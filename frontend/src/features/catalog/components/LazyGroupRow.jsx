import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Slot } from '@/core/featureKit';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { catalogKeys, fetchChannels, toCard } from '../api';

/** A catalogue group row that only fetches once it scrolls near the viewport. */
export function LazyGroupRow({ group, kind, onSelect }) {
  const anchor = useRef(null);
  // Without IntersectionObserver (old browsers, jsdom) every row loads eagerly.
  const [visible, setVisible] = useState(() => !('IntersectionObserver' in window));

  useEffect(() => {
    const node = anchor.current;
    if (!node || visible) return undefined;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setVisible(true), { rootMargin: '600px 0px' });
    io.observe(node);
    return () => io.disconnect();
  }, [visible]);

  const { data } = useQuery({
    queryKey: catalogKeys.group(group.name, kind),
    queryFn: ({ signal }) => fetchChannels({ group: group.name, kind, signal }),
    enabled: visible,
  });

  return (
    <div ref={anchor} style={{ minHeight: data ? undefined : 180 }}>
      {data && (
        <ContentRow
          title={group.name}
          subtitle={data.total > data.items.length ? `${data.total} içerik` : undefined}
          items={data.items.map(toCard)}
          onSelect={onSelect}
          actions={(item) => <Slot name="content.actions" item={item} />}
        />
      )}
    </div>
  );
}
