"""Notifications: transactional e-mail.

Other modules queue mail through the ``notifications.email`` capability and
contribute their own templates to ``notifications.templates``; delivery runs
asynchronously over the transactional outbox (retries, dead letters, exactly-
once via the inbox). Transports plug into ``notifications.email_senders``.
"""
