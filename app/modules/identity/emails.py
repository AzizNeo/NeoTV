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
_FOOTER_EN = "\n\n— NeoTV\nIf you did not ask for this e-mail, you can ignore it."

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


#: English variants: same keys, same placeholders (the catalogue refuses a translation that differs).
TEMPLATES_EN = (
    EmailTemplate(
        key=VERIFY_EMAIL,
        locale="en",
        subject="NeoTV: verify your e-mail address",
        text=(
            "Hi {username},\n\nClick the link to verify your e-mail address "
            "(valid for {hours} hours):\n\n{link}" + _FOOTER_EN
        ),
        html=(
            "<p>Hi {username},</p><p>Click the link to verify your e-mail address "
            '(valid for {hours} hours):</p><p><a href="{link}">Verify my e-mail</a></p>'
        ),
    ),
    EmailTemplate(
        key=PASSWORD_RESET,
        locale="en",
        subject="NeoTV: reset your password",
        text=(
            "Hi {username},\n\nClick the link to reset your password "
            "(valid for {minutes} minutes, single use):\n\n{link}" + _FOOTER_EN
        ),
        html=(
            "<p>Hi {username},</p><p>Click the link to reset your password "
            '(valid for {minutes} minutes, single use):</p><p><a href="{link}">Set a new password</a></p>'
        ),
    ),
    EmailTemplate(
        key=PASSWORD_CHANGED,
        locale="en",
        subject="NeoTV: your password was changed",
        text=(
            "Hi {username},\n\nYour account password was changed and every device was signed out.\n"
            "If this wasn't you, set a new password right away with 'Forgot password'.\n\n— NeoTV"
        ),
    ),
    EmailTemplate(
        key=EMAIL_CHANGE_CONFIRM,
        locale="en",
        subject="NeoTV: confirm your new e-mail address",
        text=(
            "Hi {username},\n\nClick the link to make this address your NeoTV account's e-mail "
            "(valid for {hours} hours, single use):\n\n{link}" + _FOOTER_EN
        ),
        html=(
            "<p>Hi {username},</p><p>Click the link to make this address your NeoTV account's e-mail "
            '(valid for {hours} hours, single use):</p><p><a href="{link}">Confirm my new address</a></p>'
        ),
    ),
    EmailTemplate(
        key=EMAIL_CHANGE_REQUESTED,
        locale="en",
        subject="NeoTV: e-mail change requested",
        text=(
            "Hi {username},\n\nWe received a request to change your account's e-mail to {new_email}. "
            "The change happens once the new address is confirmed.\n"
            "If this wasn't you, change your password right away.\n\n— NeoTV"
        ),
    ),
    EmailTemplate(
        key=EMAIL_CHANGED,
        locale="en",
        subject="NeoTV: your e-mail address was changed",
        text=(
            "Hi {username},\n\nYour account's e-mail address was changed to {new_email}.\n"
            "If this wasn't you, undo it with the link below; every session is signed out and a password "
            "reset link is sent to this address (valid for {days} days):\n\n{link}\n\n— NeoTV"
        ),
        html=(
            "<p>Hi {username},</p><p>Your account's e-mail address was changed to <b>{new_email}</b>.</p>"
            "<p>If this wasn't you, undo it; every session is signed out and a password reset link is sent to "
            'this address (valid for {days} days):</p><p><a href="{link}">Undo the change</a></p>'
        ),
    ),
    EmailTemplate(
        key=NEW_DEVICE_SIGN_IN,
        locale="en",
        subject="NeoTV: new sign-in from a device",
        text=(
            "Hi {username},\n\nSomeone signed in to your account from a new device:\n\n"
            "  Device: {device}\n  IP address: {ip}\n  Time: {when}\n\n"
            "If this was you, there is nothing to do.\nIf not: remove the device under Account → Devices "
            "and change your password right away.\n\n— NeoTV"
        ),
    ),
)


def templates(_container: Any) -> tuple[EmailTemplate, ...]:
    return TEMPLATES + TEMPLATES_EN
