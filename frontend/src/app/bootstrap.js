import { env } from '@/core/config/env';
import { buildRegistry } from '@/core/featureKit';
import { FEATURES } from '@/features';

/**
 * Backend modules that are switched on (`/api/v1/health/info`). `null` means
 * "unknown" (API unreachable at boot) → every feature stays on and the API
 * answers for itself; the UI never hard-fails because the probe failed.
 */
export async function fetchBackendModules({ fetchImpl = fetch, timeoutMs = 4000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${env.VITE_API_BASE_URL}/api/v1/health/info`, { signal: controller.signal });
    if (!response.ok) return null;
    const body = await response.json();
    const modules = body?.data?.modules;
    return modules && typeof modules === 'object' ? Object.keys(modules) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function createRegistry(options = {}) {
  const backendModules = await fetchBackendModules(options);
  return buildRegistry(FEATURES, { disabled: env.VITE_DISABLED_FEATURES, backendModules });
}
