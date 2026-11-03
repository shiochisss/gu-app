from copy import deepcopy
from threading import RLock
from typing import Protocol
from uuid import uuid4

import stripe
from urllib3.util import Timeout

from app.payments.budget import timeout


class GatewayError(Exception):
    def __init__(self, code="PROVIDER_ERROR", *, unknown=True):
        self.code = code
        self.unknown = unknown


class PaymentGateway(Protocol):
    def authorize(self, amount, token, metadata, key) -> dict: ...
    def retrieve(self, intent_id) -> dict: ...
    def search_by_order(self, order_id) -> list[dict]: ...
    def capture(self, intent_id, amount, key) -> dict: ...
    def cancel(self, intent_id, key) -> dict: ...
    def refund(self, intent_id, amount, key) -> dict: ...
    def retrieve_refund(self, refund_id) -> dict: ...
    def list_refunds(self, intent_id) -> list[dict]: ...


class BudgetRequestsClient(stripe.RequestsClient):
    @property
    def _timeout(self):
        seconds = timeout()
        return Timeout(total=seconds, connect=min(5.0, seconds), read=seconds)

    @_timeout.setter
    def _timeout(self, value):
        pass  # Per-request timeouts are computed from the current worker's context.


class StripePaymentGateway:
    def __init__(self, secret):
        self.client = stripe.StripeClient(
            secret, max_network_retries=0, http_client=BudgetRequestsClient(timeout=10)
        )

    def _call(self, method, *args, **kwargs):
        try:
            value = method(*args, **kwargs)
            return value.to_dict()
        except (
            stripe.CardError,
            stripe.InvalidRequestError,
            stripe.AuthenticationError,
            stripe.PermissionError,
            stripe.IdempotencyError,
        ) as exc:
            raise GatewayError(type(exc).__name__, unknown=False) from None
        except (stripe.StripeError, TimeoutError, OSError) as exc:
            raise GatewayError(type(exc).__name__, unknown=True) from None

    def authorize(self, amount, token, metadata, key):
        return self._call(
            self.client.v1.payment_intents.create,
            params=dict(
                amount=amount,
                currency="jpy",
                capture_method="manual",
                confirm=True,
                confirmation_token=token,
                metadata=metadata,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            ),
            options={"idempotency_key": key},
        )

    def retrieve(self, intent_id):
        return self._call(self.client.v1.payment_intents.retrieve, intent_id)

    def search_by_order(self, order_id):
        return self._call(
            self.client.v1.payment_intents.search,
            params={"query": f"metadata['order_id']:'{order_id}'"},
        )["data"]

    def capture(self, intent_id, amount, key):
        return self._call(
            self.client.v1.payment_intents.capture,
            intent_id,
            params={"amount_to_capture": amount},
            options={"idempotency_key": key},
        )

    def cancel(self, intent_id, key):
        return self._call(
            self.client.v1.payment_intents.cancel,
            intent_id,
            params={"cancellation_reason": "abandoned"},
            options={"idempotency_key": key},
        )

    def refund(self, intent_id, amount, key):
        return self._call(
            self.client.v1.refunds.create,
            params={"payment_intent": intent_id, "amount": amount},
            options={"idempotency_key": key},
        )

    def retrieve_refund(self, refund_id):
        return self._call(self.client.v1.refunds.retrieve, refund_id)

    def list_refunds(self, intent_id):
        return self._call(self.client.v1.refunds.list, params={"payment_intent": intent_id})["data"]


class FakePaymentGateway:
    """Injected by tests only. No request or environment switch enables this in the app."""

    def __init__(self, outcome="requires_capture"):
        self.outcome = outcome
        self.outcomes = {}
        self.intents = {}
        self.refunds = {}
        self.results = {}
        self.calls = []
        self.lock = RLock()

    def _mutate(self, operation, key, function):
        with self.lock:
            if key not in self.results:
                self.calls.append((operation, key))
                outcome = self.outcomes.get(operation)
                if outcome == "error":
                    self.results[key] = GatewayError("InvalidRequestError", unknown=False)
                else:
                    result = function()
                    if operation == "REFUND" and outcome in {
                        "failed",
                        "pending",
                        "requires_action",
                    }:
                        self.refunds[result["id"]]["status"] = outcome
                        result["status"] = outcome
                    self.results[key] = GatewayError() if outcome == "lost_response" else result
            result = self.results[key]
            if isinstance(result, Exception):
                raise result
            return deepcopy(result)

    def authorize(self, amount, token, metadata, key):
        def create():
            if self.outcome == "declined":
                return GatewayError("CardError", unknown=False)
            if self.outcome == "unexpected":
                return RuntimeError("test-only unexpected failure")
            status = "requires_capture" if self.outcome == "lost_response" else self.outcome
            ident = "pi_fake_" + uuid4().hex
            intent = dict(
                id=ident,
                status=status,
                amount=amount,
                amount_received=0,
                currency="jpy",
                livemode=False,
                metadata=metadata,
                client_secret=ident + "_secret_test",
            )
            self.intents[ident] = intent
            return GatewayError() if self.outcome == "lost_response" else intent

        return self._mutate("AUTHORIZE", key, create)

    def retrieve(self, intent_id):
        with self.lock:
            return deepcopy(self.intents[intent_id])

    def search_by_order(self, order_id):
        return [deepcopy(x) for x in self.intents.values() if x["metadata"]["order_id"] == order_id]

    def capture(self, intent_id, amount, key):
        def change():
            self.intents[intent_id].update(status="succeeded", amount_received=amount)
            return self.intents[intent_id]

        return self._mutate("CAPTURE", key, change)

    def cancel(self, intent_id, key):
        def change():
            self.intents[intent_id]["status"] = "canceled"
            return self.intents[intent_id]

        return self._mutate("RELEASE", key, change)

    def refund(self, intent_id, amount, key):
        def change():
            ident = "re_fake_" + uuid4().hex
            result = dict(
                id=ident,
                payment_intent=intent_id,
                amount=amount,
                status="succeeded",
                livemode=False,
            )
            self.refunds[ident] = result
            return result

        return self._mutate("REFUND", key, change)

    def retrieve_refund(self, refund_id):
        return deepcopy(self.refunds[refund_id])

    def list_refunds(self, intent_id):
        return [
            deepcopy(x)
            for x in reversed(list(self.refunds.values()))
            if x["payment_intent"] == intent_id
        ]
