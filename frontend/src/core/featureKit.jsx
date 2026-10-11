/**
 * Feature kit — the frontend half of the puzzle (mirrors the backend ModuleRegistry).
 *
 * A feature is a folder with a `manifest.js` (`defineFeature({...})`) and an
 * `index.js` (its public API). Adding a feature = one line in
 * `src/features/index.js`; removing one = deleting that line (or disabling it
 * via VITE_DISABLED_FEATURES / the backend module being off).
 *
 * Contract violations fail at startup with *named* errors — never a blank page:
 *   FeatureContractError, DuplicateRouteError, MissingFeatureError, UnknownSlotError
 *
 * Slots are the frontend extension points: a feature *declares* a slot
 * (e.g. catalog declares `home.rows`), others *contribute* components to it
 * (library → "Continue watching", recommendations → "For you"). If the
 * declaring feature is off, contributions are dropped; if nobody declares the
 * slot, that is a contract error.
 */
import { createContext, useContext, useMemo } from 'react';

export class FeatureContractError extends Error {
  constructor(feature, detail) {
    super(`[feature:${feature}] ${detail}`);
    this.name = 'FeatureContractError';
    this.feature = feature;
  }
}
export class DuplicateRouteError extends FeatureContractError {
  name = 'DuplicateRouteError';
}
export class MissingFeatureError extends FeatureContractError {
  name = 'MissingFeatureError';
}
export class UnknownSlotError extends FeatureContractError {
  name = 'UnknownSlotError';
}

// public: signed-out only · auth: signed-in · admin: + admin:access · any: both (e.g. links opened from e-mail)
const GUARDS = new Set(['public', 'auth', 'admin', 'any']);
const LAYOUTS = new Set(['shell', 'bare']);

/**
 * @typedef {{ path: string, lazy: () => Promise<{default: import('react').ComponentType}>,
 *             guard?: 'public'|'auth'|'admin'|'any', layout?: 'shell'|'bare' }} RouteDef
 * @typedef {{ to: string, label: string, icon: import('react').ComponentType<any>, order?: number,
 *             guard?: 'auth'|'admin', section?: 'main'|'account' }} NavDef
 * @typedef {{ slot: string, component: import('react').ComponentType<any>, order?: number }} Contribution
 * @typedef {{ id: string, requires?: string[], backendModule?: string, routes?: RouteDef[], nav?: NavDef[],
 *             providers?: import('react').ComponentType<{children: import('react').ReactNode}>[],
 *             slots?: string[], contributes?: Contribution[] }} FeatureManifest
 */

/** @param {FeatureManifest} manifest */
export function defineFeature(manifest) {
  if (!manifest?.id || !/^[a-z][a-z0-9-]*$/.test(manifest.id)) {
    throw new FeatureContractError(manifest?.id ?? '?', 'id must be kebab-case');
  }
  for (const slot of manifest.slots ?? []) {
    if (!slot.includes('.')) {
      throw new FeatureContractError(manifest.id, `slot '${slot}' must be namespaced ('<area>.<name>')`);
    }
  }
  return Object.freeze(manifest);
}

/**
 * @param {FeatureManifest[]} features
 * @param {{ disabled?: string[], backendModules?: string[] | null }} options
 */
export function buildRegistry(features, { disabled = [], backendModules = null } = {}) {
  const known = new Set();
  for (const feature of features) {
    if (known.has(feature.id)) throw new FeatureContractError(feature.id, 'declared twice in src/features/index.js');
    known.add(feature.id);
  }
  const unknown = disabled.filter((id) => !known.has(id));
  if (unknown.length) throw new FeatureContractError(unknown.join(','), 'VITE_DISABLED_FEATURES names unknown feature(s)');

  const backend = backendModules ? new Set(backendModules) : null;
  const active = features.filter(
    (f) => !disabled.includes(f.id) && (!f.backendModule || !backend || backend.has(f.backendModule)),
  );
  const activeIds = new Set(active.map((f) => f.id));
  for (const feature of active) {
    for (const dep of feature.requires ?? []) {
      if (!activeIds.has(dep)) {
        const why = known.has(dep) ? 'is disabled (or its backend module is off)' : 'is not installed';
        throw new MissingFeatureError(feature.id, `requires '${dep}', which ${why}`);
      }
    }
  }

  const routeOwners = new Map();
  const routes = [];
  const nav = [];
  const providers = [];
  const slotOwners = new Map();
  for (const feature of features) {
    for (const slot of feature.slots ?? []) {
      if (slotOwners.has(slot)) {
        throw new FeatureContractError(feature.id, `slot '${slot}' already declared by '${slotOwners.get(slot)}'`);
      }
      slotOwners.set(slot, feature.id);
    }
  }
  const slots = new Map();
  for (const feature of active) {
    for (const route of feature.routes ?? []) {
      const def = { guard: 'auth', layout: 'shell', ...route, feature: feature.id };
      if (!GUARDS.has(def.guard)) throw new FeatureContractError(feature.id, `route ${def.path}: unknown guard '${def.guard}'`);
      if (!LAYOUTS.has(def.layout)) throw new FeatureContractError(feature.id, `route ${def.path}: unknown layout '${def.layout}'`);
      if (routeOwners.has(def.path)) {
        throw new DuplicateRouteError(feature.id, `${def.path} is already owned by '${routeOwners.get(def.path)}'`);
      }
      routeOwners.set(def.path, feature.id);
      routes.push(def);
    }
    for (const item of feature.nav ?? []) nav.push({ order: 100, guard: 'auth', section: 'main', ...item, feature: feature.id });
    providers.push(...(feature.providers ?? []));
    for (const contribution of feature.contributes ?? []) {
      const owner = slotOwners.get(contribution.slot);
      if (!owner) throw new UnknownSlotError(feature.id, `contributes to undeclared slot '${contribution.slot}'`);
      if (!activeIds.has(owner)) continue; // declaring feature is off → contribution dropped (like backend extensions)
      const list = slots.get(contribution.slot) ?? [];
      list.push({ order: 100, ...contribution, feature: feature.id });
      slots.set(contribution.slot, list);
    }
  }
  nav.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
  for (const list of slots.values()) list.sort((a, b) => a.order - b.order);

  return Object.freeze({
    features: active,
    routes,
    nav,
    providers,
    slots,
    backendModules: backend,
    has: (id) => activeIds.has(id),
  });
}

const RegistryContext = createContext(null);

export function RegistryProvider({ registry, children }) {
  return <RegistryContext.Provider value={registry}>{children}</RegistryContext.Provider>;
}

export function useRegistry() {
  const registry = useContext(RegistryContext);
  if (!registry) throw new Error('useRegistry() outside <RegistryProvider>');
  return registry;
}

/** Is a feature active (installed, enabled, backend module on)? */
export function useFeature(id) {
  return useRegistry().has(id);
}

/** Is a backend module enabled? (`null` registry list = unknown → assume yes) */
export function useBackendModule(name) {
  const { backendModules } = useRegistry();
  return backendModules ? backendModules.has(name) : true;
}

/** Render every contribution to `name`, in order, with the same props. */
export function Slot({ name, ...props }) {
  const registry = useRegistry();
  const items = useMemo(() => registry.slots.get(name) ?? [], [registry, name]);
  // A feature may contribute several components to one slot: key by feature *and* position.
  return items.map(({ component: Component, feature }, i) => <Component key={`${feature}:${i}`} {...props} />);
}

/** Contributions to a slot (for owners that need custom layout). */
export function useSlot(name) {
  const registry = useRegistry();
  return registry.slots.get(name) ?? [];
}
