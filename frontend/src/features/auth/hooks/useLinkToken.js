import { useState } from 'react';

/**
 * Reads the one-time secret from the URL *fragment* (`#token=…`) — fragments are
 * never sent to servers, proxies or Referer headers — and scrubs it from the
 * address bar right away so it does not linger in history or screenshots.
 */
export function readLinkToken(hash = window.location.hash) {
  const token = new URLSearchParams(hash.replace(/^#/, '')).get('token');
  return token && /^[A-Za-z0-9_-]{20,200}$/.test(token) ? token : null;
}

export function useLinkToken() {
  const [token] = useState(() => {
    const value = readLinkToken();
    if (window.location.hash) {
      window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
    }
    return value;
  });
  return token;
}
