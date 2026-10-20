import { describe, expect, it } from 'vitest';
import { perks } from './api';

describe('plans', () => {
  it('promise the catch-up window the server enforces', () => {
    const t = (key, values) => `${key}${values ? `:${JSON.stringify(values)}` : ''}`;
    const base = { max_streams: 1, max_resolution: '1080p', ads: false, offline_downloads: false, max_profiles: 1 };
    expect(perks({ ...base, catchup_days: 7 }, t)).toContain('perks.catchup:{"count":7}');
    expect(perks({ ...base, catchup_days: 0 }, t).some((p) => p.startsWith('perks.catchup'))).toBe(false);
  });
});
