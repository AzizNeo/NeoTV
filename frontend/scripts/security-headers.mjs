/**
 * Reads deploy/nginx/security-headers.conf — the SPA's security headers, single source of truth —
 * so `vite preview` and the browser tests serve the production policy, not a copy that can drift.
 * Headers whose value is an nginx variable (HSTS: HTTPS only) are left out: preview is plain HTTP.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const SECURITY_HEADERS_FILE = fileURLToPath(new URL('../../deploy/nginx/security-headers.conf', import.meta.url));
const LINE = /^\s*add_header\s+([A-Za-z-]+)\s+(?:"([^"]*)"|(\$\w+))\s+always;\s*$/;

/** `{ 'Content-Security-Policy': "default-src 'self'; …", … }` */
export function readSecurityHeaders(file = SECURITY_HEADERS_FILE) {
  const headers = {};
  for (const raw of readFileSync(file, 'utf8').split('\n')) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    const match = LINE.exec(raw);
    if (!match) throw new Error(`${file}: unexpected line (keep \`add_header Name "value" always;\`): ${raw.trim()}`);
    if (match[2] !== undefined) headers[match[1]] = match[2];
  }
  if (!headers['Content-Security-Policy']) throw new Error(`${file}: no Content-Security-Policy`);
  return headers;
}
