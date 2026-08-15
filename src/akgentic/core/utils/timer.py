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
        >>> timer.cancel()         # prevents callback from firing
    """

    def __init__(self, delay: int, timeout_callback: Callable[[], None]) -> None:
        self.delay = delay
        self.timeout_callback = timeout_callback
        self.task_count: int = 0
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        """Start or restart the countdown timer.

        Cancels any existing timer before starting a new one.
        """
        self.cancel()
        self._timer = threading.Timer(self.delay, self.timeout_callback)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        """Cancel the current timer, preventing the callback from firing."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

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
