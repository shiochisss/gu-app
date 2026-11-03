from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import stripe

from app.payments.gateway import FakePaymentGateway, GatewayError, StripePaymentGateway


def test_stripe_authorization_uses_jpy_manual_capture_and_provider_key():
    gateway = StripePaymentGateway("sk_test_fixture")
    create = Mock(
        return_value=SimpleNamespace(
            to_dict=lambda: {"id": "pi_test", "status": "requires_capture"}
        )
    )
    gateway.client = SimpleNamespace(
        v1=SimpleNamespace(payment_intents=SimpleNamespace(create=create))
    )
    assert (
        gateway.authorize(1980, "ctoken_test", {"order_id": "order"}, "payment:AUTHORIZE:1")["id"]
        == "pi_test"
    )
    kwargs = create.call_args.kwargs
    assert kwargs["params"] == dict(
        amount=1980,
        currency="jpy",
        capture_method="manual",
        confirm=True,
        confirmation_token="ctoken_test",
        metadata={"order_id": "order"},
        automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
    )
    assert kwargs["options"] == {"idempotency_key": "payment:AUTHORIZE:1"}


@pytest.mark.parametrize(
    "error,unknown",
    [
        (stripe.APIConnectionError("private provider details"), True),
        (stripe.APIError("private provider details"), True),
        (stripe.RateLimitError("private provider details"), True),
        (stripe.InvalidRequestError("private provider details", "param"), False),
        (stripe.AuthenticationError("private provider details"), False),
    ],
)
def test_stripe_error_classification_does_not_copy_provider_message(error, unknown):
    gateway = StripePaymentGateway("sk_test_fixture")

    def fail():
        raise error

    with pytest.raises(GatewayError) as caught:
        gateway._call(fail)
    assert caught.value.unknown is unknown
    assert "private" not in str(caught.value)


def test_fake_gateway_provider_mutations_are_idempotent():
    gateway = FakePaymentGateway()
    first = gateway.authorize(1980, "ctoken_test", {"order_id": "order"}, "p:AUTHORIZE:1")
    assert gateway.authorize(1980, "ctoken_test", {"order_id": "order"}, "p:AUTHORIZE:1") == first
    gateway.capture(first["id"], 990, "p:CAPTURE:1")
    gateway.capture(first["id"], 990, "p:CAPTURE:1")
    assert len(gateway.calls) == 2
    refund = gateway.refund(first["id"], 990, "p:REFUND:1")
    assert gateway.refund(first["id"], 990, "p:REFUND:1") == refund
    assert len(gateway.list_refunds(first["id"])) == 1
