/**
 * Zod configuration — must run before any schema parses (imported first in main.jsx).
 *
 * `jitless`: Zod otherwise probes `new Function("")` to compile faster object parsers. Our CSP
 * (script-src 'self', no 'unsafe-eval') blocks that; Zod would fall back silently, but every page
 * would report a CSP violation. Jitless parsing is plenty fast for forms and API payloads.
 */
import { z } from 'zod';

z.config({ jitless: true });
