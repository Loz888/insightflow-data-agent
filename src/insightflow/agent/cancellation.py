"""Cooperative per-request cancellation; callbacks cannot outlive a borrowed connection."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock
from insightflow.database.errors import AgentError, ErrorKind

CURRENT_CANCELLATION = ContextVar("insightflow_cancellation", default=None)


class Cancellation:
    def __init__(self):
        self.event = Event()
        self.lock = Lock()
        self.callbacks = {}

    def check(self):
        if self.event.is_set():
            raise AgentError(ErrorKind.REQUEST_CANCELLED, "请求已取消，没有保存本轮会话事实。")

    def cancel(self):
        self.event.set()
        with self.lock:
            callbacks = list(self.callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass  # cancellation is best effort; DB timeout remains an independent bound

    @contextmanager
    def bind(self, callback):
        guard = Lock()
        active = True

        def invoke():
            with guard:
                if active:
                    callback()

        key = object()
        with self.lock:
            self.callbacks[key] = invoke
        try:
            self.check()
            yield
        finally:
            with guard:
                active = False
            with self.lock:
                self.callbacks.pop(key, None)


def check_cancelled():
    token = CURRENT_CANCELLATION.get()
    if token:
        token.check()
