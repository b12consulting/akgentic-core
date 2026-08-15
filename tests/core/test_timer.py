"""Unit tests for the Timer helper class."""

import threading
import time
from unittest.mock import MagicMock

from akgentic.core.utils.timer import Timer


class TestTimerInitialization:
    """Tests for Timer class initialization."""

    def test_timer_initializes_with_delay_and_callback(self) -> None:
        """Timer stores delay and callback correctly."""
        callback = MagicMock()
        timer = Timer(delay=60, timeout_callback=callback)

        assert timer.delay == 60
        assert timer.timeout_callback is callback

    def test_timer_initializes_task_count_to_zero(self) -> None:
        """Timer task_count starts at 0."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        assert timer.task_count == 0

    def test_timer_initializes_internal_timer_to_none(self) -> None:
        """Timer._timer starts as None before start() is called."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        assert timer._timer is None


class TestTimerStartAndCancel:
    """Tests for Timer start() and cancel() methods."""

    def test_start_creates_threading_timer(self) -> None:
        """start() creates an active threading.Timer."""
        callback = MagicMock()
        timer = Timer(delay=60, timeout_callback=callback)
        timer.start()

        try:
            assert timer._timer is not None
            assert isinstance(timer._timer, threading.Timer)
        finally:
            timer.cancel()

    def test_cancel_stops_timer(self) -> None:
        """cancel() cancels the active threading.Timer and sets it to None."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.start()
        timer.cancel()

        assert timer._timer is None

    def test_cancel_on_unstarted_timer_is_safe(self) -> None:
        """cancel() on a timer that was never started does not raise."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.cancel()  # Should not raise
        assert timer._timer is None

    def test_start_replaces_existing_timer(self) -> None:
        """Calling start() twice replaces the previous timer."""
        callback = MagicMock()
        timer = Timer(delay=60, timeout_callback=callback)
        timer.start()
        first_timer = timer._timer

        timer.start()
        try:
            assert timer._timer is not first_timer
        finally:
            timer.cancel()

    def test_timer_fires_callback_after_delay(self) -> None:
        """Timer invokes callback after the specified delay."""
        callback = MagicMock()
        # Use a real threading.Timer with a short float internally;
        # we construct it directly to keep the test fast.
        timer = Timer.__new__(Timer)
        timer.delay = 1
        timer.timeout_callback = callback
        timer.task_count = 0
        timer._timer = None
        # Start with a short internal threading.Timer for test speed
        timer._timer = threading.Timer(0.1, callback)
        timer._timer.start()

        time.sleep(0.3)
        callback.assert_called_once()

    def test_cancel_prevents_callback(self) -> None:
        """Cancelling timer before it fires prevents callback invocation."""
        callback = MagicMock()
        timer = Timer(delay=1, timeout_callback=callback)
        # Start a short internal timer for test speed
        timer._timer = threading.Timer(0.5, callback)
        timer._timer.start()
        timer.cancel()

        time.sleep(0.7)
        callback.assert_not_called()

    def test_start_drives_the_countdown_to_the_callback(self) -> None:
        """start() itself expires into the callback — not just a threading.Timer built by hand.

        The sibling fast tests install ``timer._timer`` directly, so none of them
        proves that ``start()`` wires delay and callback together. This one goes
        through the public API and waits on the real countdown.
        """
        fired = threading.Event()
        timer = Timer(delay=1, timeout_callback=fired.set)
        timer.start()

        try:
            assert fired.wait(timeout=10.0), "countdown never fired"
        finally:
            timer.cancel()

    def test_cancel_after_start_suppresses_the_countdown(self) -> None:
        """cancel() on a countdown started via start() stops it from ever firing."""
        fired = threading.Event()
        timer = Timer(delay=1, timeout_callback=fired.set)
        timer.start()
        timer.cancel()

        assert not fired.wait(timeout=2.0)


class TestTimerTaskStarted:
    """Tests for Timer.task_started() method."""

    def test_task_started_increments_task_count(self) -> None:
        """task_started() increments task_count by 1."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.task_started()
        assert timer.task_count == 1

    def test_task_started_increments_multiple_times(self) -> None:
        """Multiple task_started() calls increment count cumulatively."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.task_started()
        timer.task_started()
        timer.task_started()
        assert timer.task_count == 3

    def test_task_started_cancels_timer_when_count_positive(self) -> None:
        """task_started() cancels the running timer when count > 0."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.start()
        assert timer._timer is not None

        timer.task_started()
        assert timer._timer is None
        assert timer.task_count == 1

    def test_task_started_cancels_timer_on_subsequent_calls(self) -> None:
        """task_started() keeps timer cancelled for multiple concurrent tasks."""
        callback = MagicMock()
        timer = Timer(delay=1, timeout_callback=callback)
        # Manually place a short internal timer to speed up the test
        timer._timer = threading.Timer(0.1, callback)
        timer._timer.start()

        timer.task_started()  # count = 1, timer cancelled
        timer.task_started()  # count = 2, timer still cancelled

        time.sleep(0.3)
        callback.assert_not_called()
        assert timer.task_count == 2


class TestTimerTaskCompleted:
    """Tests for Timer.task_completed() method."""

    def test_task_completed_decrements_task_count(self) -> None:
        """task_completed() decrements task_count by 1."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.task_count = 2
        timer.task_completed()
        assert timer.task_count == 1

    def test_task_completed_starts_timer_when_count_reaches_zero(self) -> None:
        """task_completed() restarts timer when count drops to 0."""
        callback = MagicMock()
        timer = Timer(delay=60, timeout_callback=callback)
        timer.task_count = 1

        timer.task_completed()

        try:
            assert timer.task_count == 0
            assert timer._timer is not None
        finally:
            timer.cancel()

    def test_task_completed_prevents_negative_count(self) -> None:
        """task_completed() clamps task_count to 0, not negative."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.task_count = 0

        timer.task_completed()

        try:
            assert timer.task_count == 0
        finally:
            timer.cancel()

    def test_task_completed_does_not_start_timer_while_tasks_active(self) -> None:
        """task_completed() does not restart timer while other tasks are still active."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.task_count = 2

        timer.task_completed()  # count = 1, still active

        assert timer.task_count == 1
        assert timer._timer is None


class TestTimerConcurrentTaskTracking:
    """Tests for timer behaviour with multiple concurrent tasks."""

    def test_timer_resets_after_all_tasks_complete(self) -> None:
        """Timer restarts only after ALL started tasks have completed."""
        callback = MagicMock()
        timer = Timer(delay=60, timeout_callback=callback)
        timer.start()

        # Simulate 3 concurrent agents receiving messages
        timer.task_started()  # count = 1
        timer.task_started()  # count = 2
        timer.task_started()  # count = 3

        # Simulate 2 completing
        timer.task_completed()  # count = 2 — timer stays off
        timer.task_completed()  # count = 1 — timer stays off
        assert timer._timer is None

        # Last task completes
        timer.task_completed()  # count = 0 — timer restarts
        try:
            assert timer._timer is not None
            assert timer.task_count == 0
        finally:
            timer.cancel()

    def test_full_start_complete_cycle_restarts_timer(self) -> None:
        """Full task cycle: start → task_started → task_completed → timer active again."""
        callback = MagicMock()
        timer = Timer(delay=60, timeout_callback=callback)
        timer.start()

        timer.task_started()  # pauses timer
        assert timer._timer is None

        timer.task_completed()  # restarts timer when count=0
        try:
            assert timer._timer is not None
            assert timer.task_count == 0
        finally:
            timer.cancel()


class TestTimerClose:
    """Tests for Timer.close() — the terminal counterpart of cancel().

    ``cancel()`` is a resumable pause: the very next ``task_completed()`` at
    count zero calls ``start()`` again and the countdown is back. ``close()``
    is one-way: ``start()`` becomes a no-op, so nothing can re-arm it. The two
    tests at the top of this class assert that contrast side by side — it is
    the entire reason ``close()`` exists.
    """

    def test_cancel_leaves_the_timer_able_to_rearm(self) -> None:
        """After cancel(), a task_started()/task_completed() pair re-arms the countdown.

        This is the behaviour ``task_started()`` depends on, and the behaviour
        that makes ``cancel()`` insufficient for a teardown: a late
        ``task_completed()`` from a draining mailbox brings the countdown back.
        """
        fired = threading.Event()
        timer = Timer(delay=1, timeout_callback=fired.set)
        timer.start()
        timer.cancel()

        timer.task_started()
        timer.task_completed()

        try:
            assert timer._timer is not None
            assert fired.wait(timeout=10.0), "cancelled timer failed to re-arm"
        finally:
            timer.cancel()

    def test_close_leaves_the_timer_unable_to_rearm(self) -> None:
        """After close(), the identical pair does NOT re-arm — the mirror of the test above."""
        fired = threading.Event()
        timer = Timer(delay=1, timeout_callback=fired.set)
        timer.start()
        timer.close()

        timer.task_started()
        timer.task_completed()

        assert timer._timer is None
        assert not fired.wait(timeout=2.5), "closed timer re-armed and fired"

    def test_close_on_unstarted_timer_is_safe(self) -> None:
        """close() on a timer that was never started does not raise."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.close()
        assert timer._timer is None

    def test_close_is_idempotent(self) -> None:
        """Calling close() twice does not raise and does not resurrect the countdown."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.start()
        timer.close()
        timer.close()

        assert timer._timer is None

    def test_close_after_cancel_is_safe(self) -> None:
        """cancel() then close() does not raise and leaves the timer closed."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.start()
        timer.cancel()
        timer.close()

        timer.start()
        assert timer._timer is None

    def test_cancel_after_close_is_safe(self) -> None:
        """close() then cancel() does not raise and does not reopen the timer."""
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.start()
        timer.close()
        timer.cancel()

        timer.start()
        assert timer._timer is None

    def test_close_cancels_a_running_countdown(self) -> None:
        """start() → close() stops the countdown from ever reaching the callback."""
        fired = threading.Event()
        timer = Timer(delay=1, timeout_callback=fired.set)
        timer.start()
        timer.close()

        assert not fired.wait(timeout=2.5)

    def test_start_after_close_creates_no_countdown(self) -> None:
        """A direct start() on a closed timer creates nothing and never fires."""
        fired = threading.Event()
        timer = Timer(delay=1, timeout_callback=fired.set)
        timer.close()

        timer.start()

        assert timer._timer is None
        assert not fired.wait(timeout=2.5)

    def test_close_does_not_stop_the_task_counter(self) -> None:
        """A closed timer keeps counting tasks — it simply never re-arms.

        Raising on a late ``task_completed()`` from a draining mailbox is
        exactly what must not happen, so the counter stays live.
        """
        timer = Timer(delay=60, timeout_callback=MagicMock())
        timer.close()

        timer.task_started()
        assert timer.task_count == 1

        timer.task_completed()
        assert timer.task_count == 0
        assert timer._timer is None
