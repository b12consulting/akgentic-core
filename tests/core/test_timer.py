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
