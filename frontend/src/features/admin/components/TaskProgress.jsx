import PropTypes from 'prop-types';
import { useEffect } from 'react';
import { useTaskStatus } from '../hooks/useTaskStatus';

const LABEL = { PENDING: 'Sırada', STARTED: 'Başladı', PROGRESS: 'İşleniyor', SUCCESS: 'Tamamlandı', FAILURE: 'Başarısız', REVOKED: 'İptal' };

/** Live status of a background task; `onDone(status)` fires once on a terminal state. */
export function TaskProgress({ taskId, onDone }) {
  const { data } = useTaskStatus(taskId);
  const state = data?.state;
  useEffect(() => {
    if (state === 'SUCCESS' || state === 'FAILURE' || state === 'REVOKED') onDone?.(data);
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps -- fire once per terminal state
  if (!data) return <p role="status">Görev başlatıldı…</p>;
  return (
    <p role="status">
      {LABEL[state] ?? state} {data.progress ? `· %${data.progress}` : ''} {data.message ?? ''} {data.error ? `· ${data.error}` : ''}
    </p>
  );
}
TaskProgress.propTypes = { taskId: PropTypes.string.isRequired, onDone: PropTypes.func };
