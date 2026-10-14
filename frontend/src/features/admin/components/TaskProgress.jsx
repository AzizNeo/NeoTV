import PropTypes from 'prop-types';
import { useEffect } from 'react';
import { useTaskStatus } from '../hooks/useTaskStatus';
import { useT } from '../i18n';

const STATES = new Set(['PENDING', 'STARTED', 'PROGRESS', 'SUCCESS', 'FAILURE', 'REVOKED']);

/** Live status of a background task; `onDone(status)` fires once on a terminal state. */
export function TaskProgress({ taskId, onDone }) {
  const t = useT();
  const { data } = useTaskStatus(taskId);
  const state = data?.state;
  useEffect(() => {
    if (state === 'SUCCESS' || state === 'FAILURE' || state === 'REVOKED') onDone?.(data);
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps -- fire once per terminal state
  if (!data) return <p role="status">{t('task.started')}</p>;
  return (
    <p role="status">
      {STATES.has(state) ? t(`task.states.${state}`) : state} {data.progress ? `· %${data.progress}` : ''} {data.message ?? ''} {data.error ? `· ${data.error}` : ''}
    </p>
  );
}
TaskProgress.propTypes = { taskId: PropTypes.string.isRequired, onDone: PropTypes.func };
