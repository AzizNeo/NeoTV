import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  buildRegistry, defineFeature, DuplicateRouteError, FeatureContractError, MissingFeatureError, RegistryProvider, Slot, UnknownSlotError,
} from './featureKit';

const page = () => Promise.resolve({ default: () => null });
const Icon = () => null;

describe('defineFeature', () => {
  it('rejects non kebab-case ids and un-namespaced slots', () => {
    expect(() => defineFeature({ id: 'Bad_Id' })).toThrow(FeatureContractError);
    expect(() => defineFeature({ id: 'ok', slots: ['rows'] })).toThrow(/namespaced/);
  });
});

describe('buildRegistry', () => {
  const base = defineFeature({ id: 'base', slots: ['home.rows'], routes: [{ path: '/', lazy: page }] });

  it('applies route/nav defaults and sorts nav', () => {
    const extra = defineFeature({ id: 'extra', requires: ['base'], nav: [{ to: '/b', label: 'B', icon: Icon, order: 2 }, { to: '/a', label: 'A', icon: Icon, order: 1 }] });
    const registry = buildRegistry([base, extra]);
    expect(registry.routes[0]).toMatchObject({ guard: 'auth', layout: 'shell', feature: 'base' });
    expect(registry.nav.map((n) => n.label)).toEqual(['A', 'B']);
  });

  it('names every contract violation', () => {
    expect(() => buildRegistry([base, base])).toThrow(/declared twice/);
    expect(() => buildRegistry([base, defineFeature({ id: 'dup', routes: [{ path: '/', lazy: page }] })])).toThrow(DuplicateRouteError);
    expect(() => buildRegistry([defineFeature({ id: 'x', requires: ['ghost'] })])).toThrow(MissingFeatureError);
    expect(() => buildRegistry([defineFeature({ id: 'x', contributes: [{ slot: 'nope.slot', component: Icon }] })])).toThrow(UnknownSlotError);
    expect(() => buildRegistry([base], { disabled: ['ghost'] })).toThrow(/unknown feature/);
    expect(() => buildRegistry([defineFeature({ id: 'x', routes: [{ path: '/x', lazy: page, guard: 'vip' }] })])).toThrow(/unknown guard/);
  });

  it('disabling a required feature fails loudly, an optional one silently drops contributions', () => {
    const dependent = defineFeature({ id: 'dependent', requires: ['base'] });
    expect(() => buildRegistry([base, dependent], { disabled: ['base'] })).toThrow(MissingFeatureError);

    const contributor = defineFeature({ id: 'contributor', contributes: [{ slot: 'home.rows', component: Icon }] });
    expect(buildRegistry([base, contributor], { disabled: ['base'] }).slots.size).toBe(0);
    expect(buildRegistry([base, contributor]).slots.get('home.rows')).toHaveLength(1);
  });

  it('drops features whose backend module is off', () => {
    const billing = defineFeature({ id: 'billing', backendModule: 'billing' });
    expect(buildRegistry([base, billing], { backendModules: ['identity'] }).has('billing')).toBe(false);
    expect(buildRegistry([base, billing], { backendModules: null }).has('billing')).toBe(true);
  });
});

describe('<Slot>', () => {
  it('renders contributions in order with shared props', () => {
    const owner = defineFeature({ id: 'owner', slots: ['home.rows'] });
    const a = defineFeature({ id: 'a', contributes: [{ slot: 'home.rows', order: 2, component: ({ who }) => <p>A {who}</p> }] });
    const b = defineFeature({ id: 'b', contributes: [{ slot: 'home.rows', order: 1, component: ({ who }) => <p>B {who}</p> }] });
    render(<RegistryProvider registry={buildRegistry([owner, a, b])}><Slot name="home.rows" who="x" /></RegistryProvider>);
    expect(screen.getAllByText(/x$/).map((n) => n.textContent)).toEqual(['B x', 'A x']);
  });
});
