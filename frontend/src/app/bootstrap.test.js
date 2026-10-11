import { describe, expect, it } from 'vitest';
import { buildRegistry } from '@/core/featureKit';
import { FEATURES } from '@/features';
import { fetchBackendModules } from './bootstrap';
import { buildRouteTree } from './createAppRouter';

const reply = (status, body) => () => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

describe('installed features', () => {
  it('form a valid registry with every backend module on', () => {
    const registry = buildRegistry(FEATURES);
    expect(registry.features).toHaveLength(FEATURES.length);
    expect(registry.routes.some((r) => r.path === '/admin/*' && r.guard === 'admin')).toBe(true);
    // Links opened from e-mail must work signed in *and* signed out.
    expect(registry.routes.filter((r) => r.guard === 'any').map((r) => r.path).sort()).toEqual(['/confirm-email-change', '/reset-password', '/revert-email-change', '/verify-email']);
    expect(buildRouteTree(registry)).toHaveLength(1);
  });

  it('degrade cleanly when optional backend modules are off', () => {
    const registry = buildRegistry(FEATURES, { backendModules: ['identity', 'profile', 'playback', 'catalog', 'live'] });
    for (const id of ['billing', 'library', 'recommendations', 'devices', 'admin']) expect(registry.has(id)).toBe(false);
    expect(registry.slots.get('home.rows') ?? []).toHaveLength(0);
  });
});

describe('fetchBackendModules', () => {
  it('reads module names from /health/info', async () => {
    const modules = await fetchBackendModules({ fetchImpl: reply(200, { success: true, data: { modules: { identity: '2.0', drm: '1.0' } } }) });
    expect(modules).toEqual(['identity', 'drm']);
  });

  it('returns null (= unknown, keep features on) when the probe fails', async () => {
    expect(await fetchBackendModules({ fetchImpl: reply(503, {}) })).toBeNull();
    expect(await fetchBackendModules({ fetchImpl: () => Promise.reject(new TypeError('offline')) })).toBeNull();
  });
});
