import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Client errors are answers, not glitches: never retry 4xx.
      retry: (failures, error) => (error?.status >= 400 && error?.status < 500 ? false : failures < 2),
    },
    mutations: { retry: false },
  },
});
