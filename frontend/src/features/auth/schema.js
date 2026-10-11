import { z } from 'zod';

// Mirrors the backend policy (identity/domain.py) so users get instant feedback;
// the server remains the authority and its codes are shown on mismatch.
export const loginSchema = z.object({
  username: z.string().trim().min(1, 'Kullanıcı adı gerekli'),
  password: z.string().min(1, 'Şifre gerekli'),
});

export const passwordRule = z
  .string()
  .min(10, 'En az 10 karakter')
  .max(128, 'En fazla 128 karakter')
  .refine((p) => new Set(p).size >= 4, 'En az 4 farklı karakter')
  .refine(
    (p) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length >= 2,
    'Küçük harf, büyük harf, rakam ve simgeden en az ikisini kullanın',
  );

export const registerSchema = z
  .object({
    username: z
      .string()
      .trim()
      .regex(/^[A-Za-z0-9_.-]{3,64}$/, '3-64 karakter: harf, rakam, nokta, tire, alt çizgi'),
    email: z.union([z.literal(''), z.string().trim().email('Geçerli bir e-posta girin')]),
    password: passwordRule,
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Şifreler eşleşmiyor' })
  .refine((v) => !v.username || !v.password.toLowerCase().includes(v.username.toLowerCase()), {
    path: ['password'],
    message: 'Şifre kullanıcı adını içeremez',
  });

export const changePasswordSchema = z
  .object({ current: z.string().min(1, 'Mevcut şifre gerekli'), next: passwordRule, confirm: z.string() })
  .refine((v) => v.next === v.confirm, { path: ['confirm'], message: 'Şifreler eşleşmiyor' });

export const forgotPasswordSchema = z.object({
  email: z.string().trim().min(1, 'E-posta gerekli').email('Geçerli bir e-posta girin'),
});

export const resetPasswordSchema = z
  .object({ password: passwordRule, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Şifreler eşleşmiyor' });

export const changeEmailSchema = z.object({
  email: z.string().trim().min(1, 'E-posta gerekli').email('Geçerli bir e-posta girin'),
  password: z.string().min(1, 'Mevcut şifre gerekli'),
});
