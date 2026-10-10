import { z } from 'zod';

const csv = z
  .string()
  .default('')
  .transform((value) => value.split(',').map((s) => s.trim()).filter(Boolean));

const schema = z.object({
  VITE_API_BASE_URL: z.string().default(''), // '' = same origin (dev proxy / nginx)
  VITE_DISABLED_FEATURES: csv,
});

const parsed = schema.safeParse({
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
  VITE_DISABLED_FEATURES: import.meta.env.VITE_DISABLED_FEATURES,
});

if (!parsed.success) {
  throw new Error(`Invalid frontend environment: ${parsed.error.message}`);
}

export const env = Object.freeze(parsed.data);
