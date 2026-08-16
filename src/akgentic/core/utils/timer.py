"""Inactivity countdown timer.

Standalone helper that fires a callback after a period of inactivity, tracking
active tasks so the countdown only runs while nothing is in flight.
"""

import threading
from collections.abc import Callable


class Timer:
    """Helper class for inactivity timeout management.

    Tracks active tasks and triggers a timeout callback after a configurable
    delay when the caller becomes idle (task_count reaches 0).

    The timer automatically cancels itself when tasks are active and restarts
    when the caller becomes idle again.

    Two verbs stop a countdown, and they mean different things:

    * ``cancel()`` is a **resumable pause**. The countdown stops now, but the
      timer stays usable: the next ``task_completed()`` at count zero calls
      ``start()`` and the countdown is back. This is what ``task_started()``
      relies on.
    * ``close()`` is **terminal and idempotent**. ``start()`` becomes a no-op
      afterwards, so nothing — not a late ``task_completed()``, not a direct
      ``start()`` — can re-arm the countdown. Use it when the thing being
      timed is going away for good.

    Args:
        delay: Seconds of inactivity before timeout_callback is invoked.
        timeout_callback: Zero-argument callable invoked on timeout.

    Example:
        >>> def on_timeout():
        ...     print("Timed out!")
        >>> timer = Timer(delay=60, timeout_callback=on_timeout)
        >>> timer.start()
        >>> timer.task_started()   # pauses countdown
        >>> timer.task_completed() # restarts countdown
        >>> timer.cancel()         # prevents callback from firing; can restart
        >>> timer.close()          # terminal: start() is a no-op from here on
    """

    def __init__(self, delay: int, timeout_callback: Callable[[], None]) -> None:
        self.delay = delay
        self.timeout_callback = timeout_callback
        self.task_count: int = 0
        self._timer: threading.Timer | None = None
        self._closed: bool = False

    def start(self) -> None:
        """Start or restart the countdown timer.

        Cancels any existing timer before starting a new one. A no-op once
        ``close()`` has been called — this is the single re-arm path, so
        guarding it here closes every one of them.
        """
        if self._closed:
            return
        self.cancel()
        self._timer = threading.Timer(self.delay, self.timeout_callback)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        """Cancel the current timer, preventing the callback from firing.

        A resumable pause: a later ``start()`` (directly, or through
        ``task_completed()`` at count zero) restarts the countdown.
        """
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def close(self) -> None:
        """Shut the timer down for good — terminal and idempotent.

        Cancels any running countdown and makes ``start()`` a no-op, so the
        callback can never fire again. Safe on a timer that was never started,
        and safe to call twice or after ``cancel()``.

        Task counting is deliberately left alone: a closed timer that keeps
        counting is harmless, whereas one that raised on a late
        ``task_completed()`` — arriving from a mailbox still draining after
        teardown began — would not be.
        """
        self._closed = True
        self.cancel()

    def task_started(self) -> None:
        """Increment task count and cancel timer while tasks are active."""
        self.task_count += 1
        if self.task_count > 0:
            self.cancel()

    def task_completed(self) -> None:
        """Decrement task count and restart timer when the caller becomes idle."""
        self.task_count -= 1
        if self.task_count <= 0:
            self.task_count = 0  # Prevent negative count
            self.start()
