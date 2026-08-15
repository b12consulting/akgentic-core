"""Unit tests for Orchestrator timer integration."""

import logging
import os
import time
import uuid
from collections.abc import Generator
from unittest.mock import patch

import pykka
import pytest

from akgentic.core.agent_config import BaseConfig
from akgentic.core.messages.orchestrator import (
    ErrorMessage,
    ProcessedMessage,
    ReceivedMessage,
    WarningMessage,
)
from akgentic.core.orchestrator import TIMER_DELAY, EventSubscriber, Orchestrator, Timer


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


# ---------------------------------------------------------------------------
# Orchestrator timer integration tests
# ---------------------------------------------------------------------------


class TestOrchestratorTimerInitialization:
    """Tests for timer initialization in Orchestrator.on_start()."""

    def test_orchestrator_creates_timer_on_init(self) -> None:
        """Orchestrator creates a Timer instance during on_start()."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        assert isinstance(timer, Timer)

        orch_ref.stop()

    def test_orchestrator_timer_starts_immediately(self) -> None:
        """Orchestrator timer is active immediately after on_start."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        # Timer should have an active internal threading.Timer
        assert timer._timer is not None

        orch_ref.stop()

    def test_orchestrator_timer_uses_default_delay(self) -> None:
        """Orchestrator timer defaults to TIMER_DELAY when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            config = BaseConfig(name="test-orchestrator", role="Orchestrator")
            orch_ref = Orchestrator.start(config=config)
            orch = orch_ref.proxy()

            timer = orch.get_timer().get()
            assert timer.delay == TIMER_DELAY

            orch_ref.stop()

    def test_orchestrator_timer_uses_env_var_delay(self) -> None:
        """Orchestrator timer delay is set from ORCHESTRATOR_TIMEOUT_DELAY env var."""
        with patch.dict(os.environ, {"ORCHESTRATOR_TIMEOUT_DELAY": "42"}):
            config = BaseConfig(name="test-orchestrator", role="Orchestrator")
            orch_ref = Orchestrator.start(config=config)
            orch = orch_ref.proxy()

            timer = orch.get_timer().get()
            assert timer.delay == 42

            orch_ref.stop()


class TestOrchestratorTimerMessageHandlers:
    """Tests verifying timer integration with message handlers.

    Strategy: we retrieve the Timer object returned by get_timer(), then send
    a message through the actor proxy and verify the Timer's task_count changed
    as expected. This avoids the need to inject mocks into a running actor.
    """

    def _make_received_message(self) -> ReceivedMessage:
        msg_id = uuid.uuid4()
        return ReceivedMessage(message_id=msg_id)

    def _make_processed_message(self) -> ProcessedMessage:
        return ProcessedMessage(message_id=uuid.uuid4())

    def _make_error_message(self) -> ErrorMessage:
        return ErrorMessage(
            content_type="ValueError",
            content="something went wrong",
        )

    def _make_warning_message(self) -> WarningMessage:
        return WarningMessage(content="non-critical issue")

    def test_received_message_increments_task_count(self) -> None:
        """receiveMsg_ReceivedMessage calls timer.task_started() → task_count increases."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        assert timer.task_count == 0

        # We need a non-self sender; create a dummy actor to act as external sender
        dummy_config = BaseConfig(name="dummy-agent", role="Agent")

        class _DummyOrch(Orchestrator):
            pass

        dummy_ref = _DummyOrch.start(config=dummy_config)
        dummy_proxy = dummy_ref.proxy()
        sender_addr = dummy_proxy.myAddress.get()

        msg = self._make_received_message()
        orch.receiveMsg_ReceivedMessage(msg, sender_addr).get()

        # task_started() was called: timer is cancelled (count > 0 → timer = None)
        assert timer.task_count == 1
        assert timer._timer is None

        dummy_ref.stop()
        orch_ref.stop()

    def test_processed_message_decrements_task_count_and_restarts_timer(self) -> None:
        """receiveMsg_ProcessedMessage calls timer.task_completed() → timer restarts."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        # Manually set count to 1 to simulate active task
        timer.task_count = 1
        timer.cancel()  # timer was paused due to active task

        dummy_config = BaseConfig(name="dummy-agent2", role="Agent")

        class _DummyOrch2(Orchestrator):
            pass

        dummy_ref = _DummyOrch2.start(config=dummy_config)
        dummy_proxy = dummy_ref.proxy()
        sender_addr = dummy_proxy.myAddress.get()

        msg = self._make_processed_message()
        orch.receiveMsg_ProcessedMessage(msg, sender_addr).get()

        # task_completed() was called: count reaches 0, timer restarted
        assert timer.task_count == 0
        assert timer._timer is not None

        dummy_ref.stop()
        orch_ref.stop()

    def test_error_message_does_not_affect_task_count(self) -> None:
        """An ErrorMessage does NOT modify timer task_count (timer relies only on received/processed)."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        timer.task_count = 1
        timer.cancel()

        dummy_config = BaseConfig(name="dummy-agent3", role="Agent")

        class _DummyOrch3(Orchestrator):
            pass

        dummy_ref = _DummyOrch3.start(config=dummy_config)
        dummy_proxy = dummy_ref.proxy()
        sender_addr = dummy_proxy.myAddress.get()

        msg = self._make_error_message()
        orch.receiveMsg_NotificationMessage(msg, sender_addr).get()

        # Error messages should NOT decrement task_count
        assert timer.task_count == 1

        dummy_ref.stop()
        orch_ref.stop()

    def test_received_message_from_self_skips_task_started(self) -> None:
        """receiveMsg_ReceivedMessage from self does NOT increment task_count."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        initial_count = timer.task_count

        my_address = orch.myAddress.get()
        msg = self._make_received_message()
        orch.receiveMsg_ReceivedMessage(msg, my_address).get()

        assert timer.task_count == initial_count

        orch_ref.stop()

    def test_warning_message_does_not_affect_task_count(self) -> None:
        """A WarningMessage does NOT modify timer task_count."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        timer.task_count = 1
        timer.cancel()

        dummy_config = BaseConfig(name="dummy-agent4", role="Agent")

        class _DummyOrch4(Orchestrator):
            pass

        dummy_ref = _DummyOrch4.start(config=dummy_config)
        dummy_proxy = dummy_ref.proxy()
        sender_addr = dummy_proxy.myAddress.get()

        msg = self._make_warning_message()
        orch.receiveMsg_NotificationMessage(msg, sender_addr).get()

        # Warning messages should NOT decrement task_count
        assert timer.task_count == 1

        dummy_ref.stop()
        orch_ref.stop()

    def test_warning_message_is_appended_and_fanned_out(self) -> None:
        """A WarningMessage is stored and fanned out to subscribers."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()

        dummy_config = BaseConfig(name="dummy-agent5", role="Agent")

        class _DummyOrch5(Orchestrator):
            pass

        dummy_ref = _DummyOrch5.start(config=dummy_config)
        sender_addr = dummy_ref.proxy().myAddress.get()

        msg = self._make_warning_message()
        orch.receiveMsg_NotificationMessage(msg, sender_addr).get()

        assert subscriber.messages == [msg]
        assert msg in orch.messages.get()

        dummy_ref.stop()
        orch_ref.stop()

    def test_warning_message_from_self_is_ignored(self) -> None:
        """A WarningMessage sent by the orchestrator itself is neither stored nor fanned out."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()
        messages_before = len(orch.messages.get())

        my_address = orch.myAddress.get()
        orch.receiveMsg_NotificationMessage(self._make_warning_message(), my_address).get()

        assert len(orch.messages.get()) == messages_before
        assert subscriber.messages == []

        orch_ref.stop()

    def test_notification_subclasses_dispatch_through_mro(self) -> None:
        """ErrorMessage and WarningMessage both reach the one consolidated handler.

        Delivered through real actor dispatch rather than a direct method call, so this
        goes red if a subclass stops resolving to receiveMsg_NotificationMessage.
        """
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()

        dummy_config = BaseConfig(name="dummy-agent6", role="Agent")

        class _DummyOrch6(Orchestrator):
            pass

        dummy_ref = _DummyOrch6.start(config=dummy_config)
        sender_addr = dummy_ref.proxy().myAddress.get()

        error = self._make_error_message()
        error.init(sender_addr)
        warning = self._make_warning_message()
        warning.init(sender_addr)

        orch_ref.tell(error)
        orch_ref.tell(warning)

        # The actor drains its mailbox in order, so this proxy call is served after both tells
        stored = orch.messages.get()

        assert error in stored
        assert warning in stored

        # Subscribers get an address-serialized copy, so compare identity, not the whole model.
        # The concrete subclass must survive dispatch — it must not arrive as a bare
        # NotificationMessage.
        assert [type(m) for m in subscriber.messages] == [ErrorMessage, WarningMessage]
        assert [m.id for m in subscriber.messages] == [error.id, warning.id]

        dummy_ref.stop()
        orch_ref.stop()


class TestOrchestratorStop:
    """Tests for timer cancellation in Orchestrator.stop()."""

    def test_stop_cancels_timer(self) -> None:
        """Calling stop() on the orchestrator cancels the inactivity timer."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Retrieve the timer object before stopping
        timer = orch.get_timer().get()
        assert timer._timer is not None

        # Call the orchestrator's own stop() method (not the pykka ActorRef.stop())
        # This exercises the Orchestrator.stop() override that cancels the timer.
        orch.stop().get()

        # Give the actor time to fully process the stop
        time.sleep(0.1)

        # Timer should have been cancelled by the Orchestrator.stop() override
        assert timer._timer is None

    def test_orchestrator_timer_cancelled_after_stop(self) -> None:
        """on_stop() cancels the inactivity timer on the forced/native path.

        The native ``ActorRef.stop()`` runs ``on_stop()`` directly, bypassing the
        ``Orchestrator.stop()`` override that cancels the timer on the graceful
        path. ``on_stop()`` must cancel the timer unconditionally so the daemon
        Timer thread is released and no longer references the orchestrator.
        """
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        assert timer._timer is not None
        assert timer._timer.is_alive()

        # Native Pykka stop — runs on_stop() WITHOUT Orchestrator.stop().
        orch_ref.stop(block=True)

        # on_stop() cancelled the timer: no live threading.Timer remains.
        assert timer._timer is None

    def test_on_stop_timer_cancel_is_idempotent(self) -> None:
        """An already-cancelled timer (graceful path) is a no-op in on_stop()."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        # Graceful stop() cancels the timer first; on_stop() then cancels again.
        orch.stop().get()
        time.sleep(0.1)

        # Double cancellation did not raise and left the timer cleared.
        assert timer._timer is None


class _RecordingStopSubscriber:
    """Subscriber that records on_stop_request / on_stop / on_message invocations."""

    def __init__(self) -> None:
        self.stop_request_count: int = 0
        self.stop_count: int = 0
        self.messages: list[object] = []

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        """Protocol compliance — no-op for these tests."""
        pass

    def on_stop_request(self, team_id: uuid.UUID) -> None:
        self.stop_request_count += 1

    def on_stop(self, team_id: uuid.UUID) -> None:
        self.stop_count += 1

    def on_message(self, msg: object) -> None:
        self.messages.append(msg)


class TestEventSubscriberProtocol:
    """AC1: ``on_stop_request`` is part of the ``EventSubscriber`` protocol."""

    def test_on_stop_request_exists_on_protocol(self) -> None:
        """The ``EventSubscriber`` protocol exposes ``on_stop_request``."""
        assert hasattr(EventSubscriber, "on_stop_request")
        assert callable(EventSubscriber.on_stop_request)

    def test_on_stop_request_default_implementation_is_noop(self) -> None:
        """A subclass that inherits the default definition returns ``None``.

        The protocol body is ``...`` which is compiled to a ``None`` return.
        Subscribers that do not implement ``on_stop_request`` should therefore
        silently do nothing.
        """

        class _MinimalSubscriber(EventSubscriber):
            pass

        sub = _MinimalSubscriber()
        # Calling the default method must not raise and must return None
        assert sub.on_stop_request(uuid.uuid4()) is None  # type: ignore[func-returns-value]


class TestOrchestratorTimeoutHandler:
    """AC2/AC3/AC4: ``_timeout_handler`` delegates shutdown via subscribers."""

    def test_timeout_notifies_subscribers_on_stop_request(self) -> None:
        """AC2: firing the timer calls ``on_stop_request`` on every subscriber."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        sub = _RecordingStopSubscriber()
        orch.subscribe(sub).get()

        # Invoke the handler the same way ``threading.Timer`` would —
        # directly via the callback stored on the Timer. This isolates the
        # behavioural contract of ``_timeout_handler`` from scheduling noise.
        timer = orch.get_timer().get()
        timer.timeout_callback()

        # Give the actor thread a moment to process any internal messages
        # (snapshot_for_subscribers runs on the caller; subscriber calls are
        # synchronous within _notify_subscribers_lifecycle, so assertions are immediate).
        assert sub.stop_request_count == 1
        # on_stop is a separate lifecycle hook; the timeout must not trigger it
        assert sub.stop_count == 0

        orch_ref.stop()

    def test_timeout_does_not_stop_orchestrator(self) -> None:
        """AC2/AC3: the orchestrator stays alive after timer fires.

        The refactor delegates shutdown to the subscriber — the orchestrator
        no longer sends ``StopRecursively`` to itself on inactivity. This
        test verifies the actor remains alive after a real timeout fires
        without any subscriber taking action.
        """
        with patch.dict(os.environ, {"ORCHESTRATOR_TIMEOUT_DELAY": "1"}):
            config = BaseConfig(name="test-orchestrator", role="Orchestrator")
            orch_ref = Orchestrator.start(config=config)
            orch = orch_ref.proxy()

            sub = _RecordingStopSubscriber()
            orch.subscribe(sub).get()

            # Wait past the configured 1s inactivity delay so the timer fires.
            # Poll up to 3s to confirm the subscriber was notified.
            deadline = time.monotonic() + 3.0
            while sub.stop_request_count == 0 and time.monotonic() < deadline:
                time.sleep(0.1)

            # Subscriber was notified at least once
            assert sub.stop_request_count >= 1
            # Orchestrator remained alive — shutdown is the subscriber's job now
            assert orch_ref.is_alive()

            orch_ref.stop()

    def test_timeout_log_uses_actor_team_id(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC4: the inactivity log line uses the actor's ``team_id`` attribute."""
        team_id = uuid.uuid4()
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config, team_id=team_id)
        orch = orch_ref.proxy()

        try:
            timer = orch.get_timer().get()
            with caplog.at_level(logging.INFO, logger="akgentic.core.orchestrator"):
                # Fire the handler directly (same callback threading.Timer uses)
                timer.timeout_callback()

            timeout_records = [
                r for r in caplog.records if "Orchestrator timeout after" in r.getMessage()
            ]
            assert len(timeout_records) == 1
            assert f"team={team_id}" in timeout_records[0].getMessage()
        finally:
            orch_ref.stop()
