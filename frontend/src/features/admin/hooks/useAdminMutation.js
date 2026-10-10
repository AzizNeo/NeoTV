import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/shared/components/Toast/Toast';

/** Mutation that toasts the outcome and invalidates the given query keys. */
export function useAdminMutation(mutationFn, { invalidate = [], success, onSuccess } = {}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn,
    onSuccess: (data, vars) => {
      if (success) toast.success(typeof success === 'function' ? success(data, vars) : success);
      for (const key of invalidate) queryClient.invalidateQueries({ queryKey: key });
      onSuccess?.(data, vars);
    },
    onError: (err) => toast.error(err.userMessage),
  });
}
