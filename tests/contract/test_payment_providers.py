"""Contract every PaymentProvider adapter must satisfy.

Adding a PSP adapter = add a factory to PROVIDERS; this suite then proves it
honours the same webhook-security guarantees as the existing ones.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest

from app.modules.billing.domain import UnknownProviderError, WebhookReplayError, WebhookSignatureError
from app.modules.billing.providers import (
    SIGNATURE_HEADER,
    FakePaymentProvider,
    HmacPaymentProvider,
    PaymentProvider,
    PaymentProviderRegistry,
    sign_payload,
)

SECRET = b"whsec-test-0123456789"

PROVIDERS: dict[str, Callable[[], PaymentProvider]] = {
    "hmac": lambda: HmacPaymentProvider(secret=SECRET, checkout_url_template="https://pay.example/c/{session_id}"),
    "fake": lambda: FakePaymentProvider(secret=SECRET, frontend_base_url="http://localhost:5173/"),
}


def _body(**data: object) -> bytes:
    payload = {
        "id": "evt_1",
        "type": "payment.succeeded",
        "created": int(time.time()),
        "data": {"user_id": 7, "plan": "duo", "checkout_id": "cs_1", **data},
    }
    return json.dumps(payload).encode()


@pytest.fixture(params=sorted(PROVIDERS))
def provider(request: pytest.FixtureRequest) -> PaymentProvider:
    return PROVIDERS[request.param]()


def test_checkout_sessions_are_unique_and_redirectable(provider: PaymentProvider) -> None:
    first = provider.create_checkout(user_id=1, plan="duo", idempotency_key="k", return_url="http://r")
    second = provider.create_checkout(user_id=1, plan="duo", idempotency_key="k2", return_url="http://r")
    assert first.session_id != second.session_id
    assert first.session_id in first.redirect_url and first.redirect_url.startswith("http")


def test_valid_signature_yields_typed_event(provider: PaymentProvider) -> None:
    body = _body()
    event = provider.verify_webhook(raw_body=body, headers={SIGNATURE_HEADER: sign_payload(SECRET, body)})
    assert (event.event_id, event.type, event.user_id, event.plan) == ("evt_1", "payment.succeeded", 7, "duo")


@pytest.mark.parametrize(
    "header_for",
    [
        lambda body: None,  # missing
        lambda body: "garbage",  # malformed
        lambda body: sign_payload(b"wrong-secret", body),  # wrong key
        lambda body: sign_payload(SECRET, body + b" "),  # body tampered after signing
    ],
)
def test_bad_signatures_rejected(provider: PaymentProvider, header_for: Callable[[bytes], str | None]) -> None:
    body = _body()
    header = header_for(body)
    with pytest.raises(WebhookSignatureError):
        provider.verify_webhook(raw_body=body, headers={SIGNATURE_HEADER: header} if header else {})


def test_replayed_signature_rejected(provider: PaymentProvider) -> None:
    body = _body()
    old = sign_payload(SECRET, body, timestamp=int(time.time()) - 3600)
    with pytest.raises(WebhookReplayError):
        provider.verify_webhook(raw_body=body, headers={SIGNATURE_HEADER: old})


def test_signed_but_invalid_payload_rejected(provider: PaymentProvider) -> None:
    body = json.dumps({"id": "evt", "type": "x", "data": {}}).encode()
    with pytest.raises(WebhookSignatureError):
        provider.verify_webhook(raw_body=body, headers={SIGNATURE_HEADER: sign_payload(SECRET, body)})


def test_registry_names_unknown_providers() -> None:
    registry = PaymentProviderRegistry([PROVIDERS["fake"]()], default="fake")
    with pytest.raises(UnknownProviderError):
        registry.get("stripe")
    with pytest.raises(ValueError):
        PaymentProviderRegistry([PROVIDERS["fake"]()], default="hmac")
