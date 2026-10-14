import { z } from 'zod';

// Mirrors the backend policy (identity/domain.py) so users get instant feedback;
// messages are keys of the auth catalog (i18n.js): forms show them as t(error.message).
// the server remains the authority and its codes are shown on mismatch.
export const loginSchema = z.object({
  username: z.string().trim().min(1, 'v.usernameRequired'),
  password: z.string().min(1, 'v.passwordRequired'),
});

export const passwordRule = z
  .string()
  .min(10, 'v.min10')
  .max(128, 'v.max128')
  .refine((p) => new Set(p).size >= 4, 'v.distinct4')
  .refine(
    (p) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length >= 2,
    'v.classes2',
  );

export const registerSchema = z
  .object({
    username: z
      .string()
      .trim()
      .regex(/^[A-Za-z0-9_.-]{3,64}$/, 'v.usernameFormat'),
    email: z.union([z.literal(''), z.string().trim().email('v.emailInvalid')]),
    password: passwordRule,
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'v.mismatch' })
  .refine((v) => !v.username || !v.password.toLowerCase().includes(v.username.toLowerCase()), {
    path: ['password'],
    message: 'v.containsUsername',
  });

export const changePasswordSchema = z
  .object({ current: z.string().min(1, 'v.currentRequired'), next: passwordRule, confirm: z.string() })
  .refine((v) => v.next === v.confirm, { path: ['confirm'], message: 'v.mismatch' });

export const forgotPasswordSchema = z.object({
  email: z.string().trim().min(1, 'v.emailRequired').email('v.emailInvalid'),
});

export const resetPasswordSchema = z
  .object({ password: passwordRule, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'v.mismatch' });

export const changeEmailSchema = z.object({
  email: z.string().trim().min(1, 'v.emailRequired').email('v.emailInvalid'),
  password: z.string().min(1, 'v.currentRequired'),
});
