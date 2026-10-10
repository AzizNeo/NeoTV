import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';

const TERMINAL = new Set(['SUCCESS', 'FAILURE', 'REVOKED']);

/** Polls /api/v1/tasks/<id> every second until the task reaches a terminal state. */
export function useTaskStatus(taskId) {
  return useQuery({
    queryKey: ['tasks', taskId],
    queryFn: () => api.call('kernel_tasks_task_status', { params: { task_id: taskId } }),
    enabled: Boolean(taskId),
    refetchInterval: (query) => (TERMINAL.has(query.state.data?.state) ? false : 1000),
  });
}
export const isTerminal = (state) => TERMINAL.has(state);
