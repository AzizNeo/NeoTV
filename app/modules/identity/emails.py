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
EMAIL_CHANGE_CONFIRM = "identity.email_change_confirm"
EMAIL_CHANGE_REQUESTED = "identity.email_change_requested"
EMAIL_CHANGED = "identity.email_changed"
NEW_DEVICE_SIGN_IN = "identity.new_device_sign_in"

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
    EmailTemplate(
        key=EMAIL_CHANGE_CONFIRM,
        subject="NeoTV: yeni e-posta adresinizi onaylayın",
        text=(
            "Merhaba {username},\n\nBu adresi NeoTV hesabınızın yeni e-postası yapmak için bağlantıya tıklayın "
            "({hours} saat geçerlidir, tek kullanımlıktır):\n\n{link}" + _FOOTER
        ),
        html=(
            "<p>Merhaba {username},</p><p>Bu adresi NeoTV hesabınızın yeni e-postası yapmak için bağlantıya tıklayın "
            '({hours} saat geçerlidir, tek kullanımlıktır):</p><p><a href="{link}">Yeni adresimi onayla</a></p>'
        ),
    ),
    EmailTemplate(
        key=EMAIL_CHANGE_REQUESTED,
        subject="NeoTV: e-posta değişikliği istendi",
        text=(
            "Merhaba {username},\n\nHesabınızın e-posta adresini {new_email} olarak değiştirme isteği alındı. "
            "Değişiklik, yeni adres onaylanınca gerçekleşir.\n"
            "Bu isteği siz yapmadıysanız hemen şifrenizi değiştirin.\n\n— NeoTV"
        ),
    ),
    EmailTemplate(
        key=EMAIL_CHANGED,
        subject="NeoTV: e-posta adresiniz değiştirildi",
        text=(
            "Merhaba {username},\n\nHesabınızın e-posta adresi {new_email} olarak değiştirildi.\n"
            "Bu işlemi siz yapmadıysanız aşağıdaki bağlantıyla geri alın; tüm oturumlar kapatılır ve şifre "
            "sıfırlama bağlantısı bu adrese gönderilir ({days} gün geçerlidir):\n\n{link}\n\n— NeoTV"
        ),
        html=(
            "<p>Merhaba {username},</p><p>Hesabınızın e-posta adresi <b>{new_email}</b> olarak değiştirildi.</p>"
            "<p>Bu işlemi siz yapmadıysanız geri alın; tüm oturumlar kapatılır ve şifre sıfırlama bağlantısı bu "
            'adrese gönderilir ({days} gün geçerlidir):</p><p><a href="{link}">Değişikliği geri al</a></p>'
        ),
    ),
    EmailTemplate(
        key=NEW_DEVICE_SIGN_IN,
        subject="NeoTV: yeni bir cihazdan giriş yapıldı",
        text=(
            "Merhaba {username},\n\nHesabınıza yeni bir cihazdan giriş yapıldı:\n\n"
            "  Cihaz: {device}\n  IP adresi: {ip}\n  Zaman: {when}\n\n"
            "Bu sizseniz bir şey yapmanıza gerek yok.\nSiz değilseniz: Hesap → Cihazlar bölümünden bu cihazı "
            "kaldırın ve şifrenizi hemen değiştirin.\n\n— NeoTV"
        ),
    ),
)


def templates(_container: Any) -> tuple[EmailTemplate, ...]:
    return TEMPLATES
