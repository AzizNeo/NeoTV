"""E-mail templates owned by identity, contributed to ``notifications.templates``.

If the notifications module is disabled the contribution is dropped by the
kernel (and recovery endpoints answer EMAIL_DELIVERY_UNAVAILABLE).
"""

from __future__ import annotations

from typing import Any

from app.modules.notifications.api import EmailTemplate

VERIFY_EMAIL = "identity.verify_email"
PASSWORD_RESET = "identity.password_reset"  # noqa: S105 - template key
PASSWORD_CHANGED = "identity.password_changed"  # noqa: S105 - template key

_FOOTER = "\n\n— NeoTV\nBu e-postayı siz istemediyseniz yok sayabilirsiniz."

TEMPLATES = (
    EmailTemplate(
        key=VERIFY_EMAIL,
        subject="NeoTV: e-posta adresinizi doğrulayın",
        text=(
            "Merhaba {username},\n\nE-posta adresinizi doğrulamak için bağlantıya tıklayın "
            "({hours} saat geçerlidir):\n\n{link}" + _FOOTER
        ),
        html=(
            "<p>Merhaba {username},</p><p>E-posta adresinizi doğrulamak için bağlantıya tıklayın "
            '({hours} saat geçerlidir):</p><p><a href="{link}">E-postamı doğrula</a></p>'
        ),
    ),
    EmailTemplate(
        key=PASSWORD_RESET,
        subject="NeoTV: şifre sıfırlama",
        text=(
            "Merhaba {username},\n\nŞifrenizi sıfırlamak için bağlantıya tıklayın "
            "({minutes} dakika geçerlidir, tek kullanımlıktır):\n\n{link}" + _FOOTER
        ),
        html=(
            "<p>Merhaba {username},</p><p>Şifrenizi sıfırlamak için bağlantıya tıklayın "
            '({minutes} dakika geçerlidir, tek kullanımlıktır):</p><p><a href="{link}">Yeni şifre belirle</a></p>'
        ),
    ),
    EmailTemplate(
        key=PASSWORD_CHANGED,
        subject="NeoTV: şifreniz değiştirildi",
        text=(
            "Merhaba {username},\n\nHesabınızın şifresi değiştirildi ve tüm cihazlardaki oturumlar kapatıldı.\n"
            "Bu işlemi siz yapmadıysanız hemen 'Şifremi unuttum' ile yeni şifre belirleyin.\n\n— NeoTV"
        ),
    ),
)


def templates(_container: Any) -> tuple[EmailTemplate, ...]:
    return TEMPLATES
