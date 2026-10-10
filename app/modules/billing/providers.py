"""Payment provider port + adapters.

``PaymentProvider`` is the only seam between billing and a PSP (Stripe,
iyzico, PayTR ...). Adding a PSP = one adapter class + one registration line;
the contract test suite (tests/contract/test_payment_providers.py) runs
against every adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.billing.domain import WebhookReplayError, WebhookSignatureError

SIGNATURE_HEADER = "X-NeoTV-Signature"
TOLERANCE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class CheckoutStart:
    session_id: str
    redirect_url: str


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    event_id: str
    type: str
    user_id: int
    plan: str | None
    checkout_id: str | None
    occurred_at: int
    external_subscription_id: str | None = None


class HeaderLookup(Protocol):
    """Case-insensitive header access (werkzeug ``Headers`` or a plain mapping in tests)."""

    def get(self, key: str, /) -> str | None: ...


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, *, user_id: int, plan: str, idempotency_key: str, return_url: str) -> CheckoutStart: ...
    def verify_webhook(self, *, raw_body: bytes, headers: HeaderLookup) -> ProviderEvent: ...


def sign_payload(secret: bytes, raw_body: bytes, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret, f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify_signature(secret: bytes, raw_body: bytes, header: str | None) -> dict[str, Any]:
    if not header:
        raise WebhookSignatureError("missing signature header")
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp, signature = int(parts["t"]), parts["v1"]
    except (KeyError, ValueError) as exc:
        raise WebhookSignatureError("malformed signature header") from exc
    if abs(time.time() - timestamp) > TOLERANCE_SECONDS:
        raise WebhookReplayError("signature timestamp outside tolerance")
    expected = hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookSignatureError("signature mismatch")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise WebhookSignatureError("body is not JSON") from exc
    if not isinstance(payload, dict):
        raise WebhookSignatureError("body must be a JSON object")
    return payload


def _event_from_payload(payload: dict[str, Any], timestamp_default: int) -> ProviderEvent:
    try:
        data = payload["data"]
        return ProviderEvent(
            event_id=str(payload["id"]),
            type=str(payload["type"]),
            user_id=int(data["user_id"]),
            plan=data.get("plan"),
            checkout_id=data.get("checkout_id"),
            occurred_at=int(payload.get("created", timestamp_default)),
            external_subscription_id=data.get("subscription_id"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WebhookSignatureError(f"invalid event payload: {exc}") from exc


class HmacPaymentProvider:
    """Generic hosted-checkout PSP: redirect to ``checkout_url_template``, HMAC-signed webhooks."""

    name = "hmac"

    def __init__(self, *, secret: bytes, checkout_url_template: str) -> None:
        if "{session_id}" not in checkout_url_template:
            raise ValueError("checkout_url_template must contain {session_id}")
        self._secret = secret
        self._template = checkout_url_template

    def create_checkout(self, *, user_id: int, plan: str, idempotency_key: str, return_url: str) -> CheckoutStart:
        session_id = f"cs_{secrets.token_urlsafe(18)}"
        return CheckoutStart(session_id, self._template.format(session_id=session_id, plan=plan, return_url=return_url))

    def verify_webhook(self, *, raw_body: bytes, headers: HeaderLookup) -> ProviderEvent:
        payload = verify_signature(self._secret, raw_body, headers.get(SIGNATURE_HEADER))
        return _event_from_payload(payload, int(time.time()))


class FakePaymentProvider:
    """Development/test PSP. The "checkout page" is the frontend route
    ``/billing/checkout/fake``; completing it calls a dev-only endpoint that
    produces a *properly signed* webhook — the production code path is exercised end to end."""

    name = "fake"

    def __init__(self, *, secret: bytes, frontend_base_url: str) -> None:
        self._secret = secret
        self._frontend = frontend_base_url.rstrip("/")

    def create_checkout(self, *, user_id: int, plan: str, idempotency_key: str, return_url: str) -> CheckoutStart:
        session_id = f"fake_{secrets.token_urlsafe(18)}"
        return CheckoutStart(session_id, f"{self._frontend}/billing/checkout/fake?session={session_id}&plan={plan}")

    def verify_webhook(self, *, raw_body: bytes, headers: HeaderLookup) -> ProviderEvent:
        payload = verify_signature(self._secret, raw_body, headers.get(SIGNATURE_HEADER))
        return _event_from_payload(payload, int(time.time()))

    def signed_event(
        self, *, event_type: str, user_id: int, plan: str | None, checkout_id: str | None
    ) -> tuple[bytes, dict[str, str]]:
        body = json.dumps(
            {
                "id": f"evt_{secrets.token_hex(10)}",
                "type": event_type,
                "created": int(time.time()),
                "data": {"user_id": user_id, "plan": plan, "checkout_id": checkout_id},
            },
            separators=(",", ":"),
        ).encode()
        return body, {SIGNATURE_HEADER: sign_payload(self._secret, body)}


class PaymentProviderRegistry:
    def __init__(self, providers: list[PaymentProvider], default: str) -> None:
        self._providers = {p.name: p for p in providers}
        if default not in self._providers:
            raise ValueError(f"default payment provider '{default}' is not registered")
        self._default = default

    @property
    def default(self) -> PaymentProvider:
        return self._providers[self._default]

    def get(self, name: str) -> PaymentProvider:
        from app.modules.billing.domain import UnknownProviderError

        try:
            return self._providers[name]
        except KeyError:
            raise UnknownProviderError(f"unknown payment provider '{name}'") from None
