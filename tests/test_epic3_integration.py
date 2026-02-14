"""Integration tests for Epic 3: Orchestrator inactivity timer.

Tests the full end-to-end behaviour of the Orchestrator's inactivity timer,
verifying that:
  - ReceivedMessage pauses the timer (task_started)
  - ProcessedMessage restarts the timer (task_completed)
  - Orchestrator stops after timeout when no new messages arrive
  - Manual stop cancels the timer cleanly
"""

import time
import uuid
from collections.abc import Generator
from unittest.mock import patch

import os
import pykka
import pytest

from akgentic.agent_config import BaseConfig
from akgentic.messages.message import UserMessage
from akgentic.messages.orchestrator import ProcessedMessage, ReceivedMessage
from akgentic.orchestrator import Orchestrator, Timer


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


def _make_external_sender_address(name: str = "test-agent"):
    """Create a real actor address to use as an external sender."""

    class _SenderOrch(Orchestrator):
        pass

    sender_ref = _SenderOrch.start(config=BaseConfig(name=name, role="Agent"))
    addr = sender_ref.proxy().myAddress.get()
    return sender_ref, addr


class TestOrchestratorTimerIntegration:
    """End-to-end integration tests for the inactivity timer workflow."""

    def test_received_message_pauses_timer(self) -> None:
        """ReceivedMessage triggers task_started: timer is paused (task_count > 0)."""
        config = BaseConfig(name="orch-integration", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        assert timer.task_count == 0

        sender_ref, sender_addr = _make_external_sender_address("agent-1")

        inner = UserMessage(content="start processing")
        msg = ReceivedMessage(message=inner)
        orch.receiveMsg_ReceivedMessage(msg, sender_addr).get()

        assert timer.task_count == 1
        assert timer._timer is None  # timer paused while task active

        sender_ref.stop()
        orch_ref.stop()

    def test_processed_message_restarts_timer(self) -> None:
        """ProcessedMessage triggers task_completed: timer restarts when idle."""
        config = BaseConfig(name="orch-integration", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()

        sender_ref, sender_addr = _make_external_sender_address("agent-2")

        # Simulate: agent receives message
        inner = UserMessage(content="processing")
        recv_msg = ReceivedMessage(message=inner)
        orch.receiveMsg_ReceivedMessage(recv_msg, sender_addr).get()
        assert timer.task_count == 1
        assert timer._timer is None

        # Simulate: agent completes processing
        proc_msg = ProcessedMessage(message_id=uuid.uuid4())
        orch.receiveMsg_ProcessedMessage(proc_msg, sender_addr).get()

        assert timer.task_count == 0
        assert timer._timer is not None  # timer restarted after idle

        sender_ref.stop()
        orch_ref.stop()

    def test_orchestrator_stops_after_timeout_with_no_new_messages(self) -> None:
        """Orchestrator stops itself after inactivity timeout if no new messages arrive.

        Uses a 1-second timeout for test speed.
        """
        with patch.dict(os.environ, {"ORCHESTRATOR_TIMEOUT_DELAY": "1"}):
            config = BaseConfig(name="orch-timeout-test", role="Orchestrator")
            orch_ref = Orchestrator.start(config=config)

            assert orch_ref.is_alive()

            # Poll until the actor dies (fires at ~1s) with a 3s hard ceiling
            deadline = time.monotonic() + 3.0
            while orch_ref.is_alive() and time.monotonic() < deadline:
                time.sleep(0.1)

            assert not orch_ref.is_alive()

    def test_timer_resets_on_new_message_after_previous_task_completes(self) -> None:
        """Timer resets correctly through multiple receive/process cycles."""
        config = BaseConfig(name="orch-cycle-test", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        sender_ref, sender_addr = _make_external_sender_address("cycle-agent")

        # Cycle 1
        orch.receiveMsg_ReceivedMessage(
            ReceivedMessage(message=UserMessage(content="msg1")), sender_addr
        ).get()
        assert timer.task_count == 1

        orch.receiveMsg_ProcessedMessage(
            ProcessedMessage(message_id=uuid.uuid4()), sender_addr
        ).get()
        assert timer.task_count == 0
        timer_after_cycle1 = timer._timer

        # Cycle 2 — new message arrives, timer cancels again
        orch.receiveMsg_ReceivedMessage(
            ReceivedMessage(message=UserMessage(content="msg2")), sender_addr
        ).get()
        assert timer.task_count == 1
        assert timer._timer is None  # timer cancelled again

        # Complete cycle 2
        orch.receiveMsg_ProcessedMessage(
            ProcessedMessage(message_id=uuid.uuid4()), sender_addr
        ).get()
        assert timer.task_count == 0
        assert timer._timer is not None  # timer active again

        sender_ref.stop()
        orch_ref.stop()

    def test_manual_stop_cancels_timer_before_timeout(self) -> None:
        """Calling stop() before timer fires properly cancels the timer."""
        config = BaseConfig(name="orch-manual-stop", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        timer = orch.get_timer().get()
        assert timer._timer is not None

        # Stop immediately via the orchestrator's stop() method
        orch.stop().get()
        time.sleep(0.1)

        assert timer._timer is None
        assert not orch_ref.is_alive()
