from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

DEADLINE = ContextVar("payment_deadline", default=None)


def timeout():
    deadline = DEADLINE.get()
    if deadline is None:
        return 10.0
    remaining = deadline - perf_counter() - 0.25
    if remaining <= 0:
        raise TimeoutError("operation budget exhausted")
    return min(10.0, remaining)


@contextmanager
def budget(deadline):
    token = DEADLINE.set(deadline)
    try:
        yield
    finally:
        DEADLINE.reset(token)
