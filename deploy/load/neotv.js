// NeoTV load test (k6): viewers browsing and watching, plus a steady stream of sign-ins.
//
//   LOAD_PASSWORD=… python -m tools.load_seed --count 50          # accounts first
//   k6 run -e BASE=http://localhost:8080 -e LOAD_PASSWORD=… -e PROFILE=smoke deploy/load/neotv.js
//
// Pass/fail comes from the production SLOs (deploy/prometheus/generate_rules.py), not from
// numbers picked for the test: API availability 99.5 %, API latency p99 ≤ 1 s.
//
// Rate limits stay ON (a test with them off measures another system). The scenarios are paced
// like real clients — one heartbeat per 10 s, sign-ins under the per-IP limit — and any 429 fails
// the run: it means the test, not the system, is wrong.
//
// Media segments are NOT fetched: the demo's sources are third-party public streams, and a load
// test must not load someone else's servers. Opening, keeping and releasing a stream is measured.
//
// Environment: BASE, LOAD_PASSWORD, PROFILE (smoke | load), VIEWERS (load: peak, default 50),
// ACCOUNTS (seeded accounts, default = peak viewers), WATCH_S (seconds per view, default 40).

import { check, fail, group, sleep } from 'k6';
import exec from 'k6/execution';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';

const BASE = (__ENV.BASE || 'http://localhost:8080').replace(/\/$/, '');
const PASSWORD = __ENV.LOAD_PASSWORD;
const PROFILE = __ENV.PROFILE || 'smoke';
const VIEWERS = Number(__ENV.VIEWERS || 50);
const WATCH_S = Number(__ENV.WATCH_S || 40);
const HEARTBEAT_S = 10; // the player's interval (playback HEARTBEAT_INTERVAL_S)
const LOGIN_SPACING_S = 0.6; // auth.login allows 2/s per IP: stay under it

const PROFILES = {
  // Does every flow work under a little concurrency? Minutes, for CI.
  smoke: {
    viewers: { executor: 'constant-vus', vus: 2, duration: '30s' },
    logins: { executor: 'constant-arrival-rate', rate: 1, timeUnit: '5s', duration: '30s', preAllocatedVUs: 1 },
  },
  // Ramp to the expected peak, hold it, ramp down.
  load: {
    viewers: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: VIEWERS },
        { duration: '3m', target: VIEWERS },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: `${WATCH_S + 10}s`,
    },
    logins: { executor: 'constant-arrival-rate', rate: 1, timeUnit: '1s', duration: '4m30s', preAllocatedVUs: 2 },
  },
};
if (!PROFILES[PROFILE]) throw new Error(`PROFILE must be one of ${Object.keys(PROFILES).join(', ')}`);
const PEAK = PROFILE === 'smoke' ? 2 : VIEWERS;
const ACCOUNTS = Number(__ENV.ACCOUNTS || PEAK);
const ENDPOINTS = [
  'auth.login', 'titles.rails', 'titles.browse', 'titles.detail', 'catalog.list',
  'playback.open', 'playback.heartbeat', 'playback.qoe', 'playback.release',
];

export const options = {
  scenarios: {
    viewers: { ...PROFILES[PROFILE].viewers, exec: 'viewer' },
    logins: { ...PROFILES[PROFILE].logins, exec: 'signIn' },
  },
  // Setup signs every account in under the login limit.
  setupTimeout: `${Math.ceil(ACCOUNTS * LOGIN_SPACING_S) + 60}s`,
  thresholds: {
    // The API SLOs. `slo:api` marks the requests the SLIs count (as Prometheus does).
    'http_req_failed{slo:api}': ['rate<0.005'],
    'http_req_duration{slo:api}': ['p(99)<1000'],
    // A 429 means the pacing is wrong; an unexpected answer means a flow is broken.
    rate_limited: ['count==0'],
    checks: ['rate>0.99'],
    // Always true: they only make k6 report each endpoint on its own (tools/k6_summary.py).
    ...Object.fromEntries(ENDPOINTS.map((n) => [`http_req_duration{name:${n}}`, ['max>=0']])),
  },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
};

const rateLimited = new Counter('rate_limited');
const playbackOpen = new Trend('playback_open_duration', true);

function headers(token, device) {
  const h = { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
  if (token) h.Authorization = `Bearer ${token}`;
  if (device) h['X-Device-ID'] = device;
  return h;
}

// Every request goes through here: one name per endpoint (not per URL), the SLO tag, 429 counting.
// `warmup`: setup's requests (cold workers, first sign-ins) are kept out of the SLO thresholds.
function call(method, path, { name, body = null, token, device, expect = [200], warmup = false } = {}) {
  if (!ENDPOINTS.includes(name)) throw new Error(`unknown endpoint name "${name}": add it to ENDPOINTS`);
  const res = http.request(method, `${BASE}${path}`, body === null ? null : JSON.stringify(body), {
    headers: headers(token, device),
    tags: { name, slo: warmup ? 'setup' : 'api' },
    responseCallback: http.expectedStatuses(...expect),
  });
  if (res.status === 429) rateLimited.add(1, { name });
  check(res, { [`${name} → ${expect.join('/')}`]: (r) => expect.includes(r.status) });
  return res;
}

// Success bodies are an envelope: {"success": true, "data": …}.
const data = (res, path) => (res.status < 300 ? res.json(path ? `data.${path}` : 'data') : null);

function login(username, warmup = false) {
  const res = call('POST', '/api/v1/auth/login', { name: 'auth.login', body: { username, password: PASSWORD }, warmup });
  return data(res, 'access_token');
}

const account = (n) => `load-${String(n).padStart(4, '0')}`;

export function setup() {
  if (!PASSWORD) fail('set LOAD_PASSWORD (the same value tools/load_seed.py used)');
  if (ACCOUNTS < PEAK) fail(`ACCOUNTS (${ACCOUNTS}) < peak viewers (${PEAK}): each viewer needs its own account`);
  const ready = http.get(`${BASE}/api/v1/health/ready`);
  if (ready.status !== 200) fail(`API not ready: ${ready.status} ${ready.body}`);

  const tokens = [];
  for (let n = 1; n <= ACCOUNTS; n += 1) {
    const token = login(account(n), true);
    if (!token) fail(`${account(n)} cannot sign in — run tools/load_seed.py --count ${ACCOUNTS} first`);
    tokens.push(token);
    sleep(LOGIN_SPACING_S);
  }
  const channels = call('GET', '/api/v1/catalog/channels?per_page=50', { name: 'catalog.list', token: tokens[0], warmup: true });
  const refs = (data(channels, 'items') || []).map((c) => `catalog:${c.id}`);
  if (refs.length === 0) fail('no channels to watch — seed the demo content (tools/seed_demo.py)');
  return { tokens, refs };
}

// One viewer = one account and one device (a reopened stream replaces its own slot).
export function viewer({ tokens, refs }) {
  const vu = exec.vu.idInTest;
  const token = tokens[(vu - 1) % tokens.length];
  const device = `k6-viewer-${vu}`;
  const opts = { token, device };

  group('browse', () => {
    call('GET', '/api/v1/titles/rails?per_rail=12', { name: 'titles.rails', ...opts });
    sleep(1 + Math.random());
    const page = call('GET', '/api/v1/titles?page=1&per_page=24', { name: 'titles.browse', ...opts });
    const slugs = data(page, 'items') || [];
    if (slugs.length) {
      sleep(1 + Math.random());
      const pick = slugs[Math.floor(Math.random() * slugs.length)].slug;
      call('GET', `/api/v1/titles/${pick}`, { name: 'titles.detail', ...opts });
    }
    sleep(1 + Math.random());
    call('GET', '/api/v1/catalog/channels?per_page=24', { name: 'catalog.list', ...opts });
  });

  group('watch', () => {
    const ref = refs[Math.floor(Math.random() * refs.length)];
    const opened = call('POST', '/api/v1/playback/sessions', {
      name: 'playback.open', body: { content_ref: ref }, expect: [201], ...opts,
    });
    playbackOpen.add(opened.timings.duration);
    if (opened.status !== 201) return;
    const session = data(opened, 'session_token');

    let watched = 0;
    while (watched < WATCH_S) {
      const step = Math.min(HEARTBEAT_S, WATCH_S - watched);
      sleep(step);
      watched += step;
      if (watched < WATCH_S) {
        call('POST', '/api/v1/playback/sessions/heartbeat', { name: 'playback.heartbeat', body: { session_token: session }, ...opts });
      }
    }
    call('POST', '/api/v1/playback/qoe', {
      name: 'playback.qoe',
      body: { content_ref: ref, session_token: session, startup_time_ms: 800, watch_duration_s: WATCH_S, device_type: 'desktop' },
      expect: [201],
      ...opts,
    });
    call('POST', '/api/v1/playback/sessions/release', { name: 'playback.release', body: { session_token: session }, ...opts });
  });
  sleep(2 + Math.random() * 3);
}

// A steady trickle of sign-ins (password hashing is the expensive part), under the per-IP limit.
export function signIn() {
  login(account(1 + Math.floor(Math.random() * ACCOUNTS)));
}
