"""Cancellation for local query work that runs outside the event loop."""

from contextlib import contextmanager
from threading import Event, Thread
import time


@contextmanager
def cancellable_query(connection, cancel: Event, timeout_seconds: float):
    finished = Event()
    deadline = time.monotonic() + timeout_seconds

    def watch():
        while not finished.wait(0.05):
            if cancel.is_set() or time.monotonic() >= deadline:
                connection.interrupt()
                return

    watcher = Thread(target=watch, daemon=True)
    watcher.start()
    try:
        yield
    finally:
        finished.set()
        watcher.join()
