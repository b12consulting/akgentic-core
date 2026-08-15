"""Integration tests for handler-error telemetry.

Verifies end to end what the orchestrator records when an agent handler raises:

  - WarningError → exactly one WarningMessage, NO ErrorMessage
  - any other exception → exactly one ErrorMessage
  - either way, ProcessedMessage is emitted exactly once, before the
    WarningMessage, and the notification threads like an ErrorMessage
    (``parent_id is None``)
"""

import time
from collections.abc import Generator
from typing import Any

import pykka
import pytest

from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.agent import Akgent, WarningError
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message
from akgentic.core.messages.orchestrator import (
    ErrorMessage,
    ProcessedMessage,
    WarningMessage,
)
from akgentic.core.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


# ---------------------------------------------------------------------------
# Test messages and agents for error-handling integration tests
# ---------------------------------------------------------------------------


class TriggerMessage(Message):
    """Message that triggers a handler which raises an exception."""

    error_type: str = "warning"  # "warning" or "runtime"


class _FailingAgent(Akgent[BaseConfig, BaseState]):
    """Agent whose handler raises WarningError or RuntimeError depending on the message."""

    def receiveMsg_TriggerMessage(self, msg: TriggerMessage, sender: Any) -> None:
        if msg.error_type == "warning":
            raise WarningError("non-critical issue")
        raise RuntimeError("critical failure")


# ---------------------------------------------------------------------------
# Integration tests: error handling telemetry
# ---------------------------------------------------------------------------


class TestHandlerErrorTelemetry:
    """End-to-end tests for the telemetry an agent emits when its handler raises.

    ``_handle_receive`` always emits a ProcessedMessage when it catches an
    exception, whatever the error type. What differs is the notification:

    WarningError → ProcessedMessage emitted, WarningMessage emitted, NO ErrorMessage.
    Other exception → ProcessedMessage emitted, ErrorMessage emitted.
    """

    def test_warning_error_sends_no_error_message(self) -> None:
        """WarningError: no ErrorMessage stored in orchestrator, one WarningMessage."""
        config = BaseConfig(name="orch-warning-test", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        orch_address = ActorAddressImpl(orch_ref)

        # Start an agent wired to this orchestrator
        agent_ref = _FailingAgent.start(
            config=BaseConfig(name="failing-agent-warning", role="Agent"),
            orchestrator=orch_address,
        )

        # Give on_start + StartMessage time to propagate
        time.sleep(0.3)

        messages_before = len(orch.messages.get())

        # Send message via tell() — this is how agents deliver messages in production.
        # The raw Message goes through _handle_receive, where isinstance(msg, Message)
        # is True, ensuring ProcessedMessage is emitted on error.
        trigger = TriggerMessage(error_type="warning")
        agent_ref.tell(trigger)

        # Allow the actor to process and telemetry to propagate
        time.sleep(0.5)

        # Verify NO ErrorMessage was recorded by the orchestrator
        messages_after = orch.messages.get()
        new_messages = messages_after[messages_before:]
        error_messages = [m for m in new_messages if isinstance(m, ErrorMessage)]
        assert len(error_messages) == 0, (
            f"WarningError should not produce ErrorMessage, got {error_messages}"
        )

        # A WarningMessage carries the warning's class name, its text, and the message
        warning_messages = [m for m in new_messages if isinstance(m, WarningMessage)]
        assert len(warning_messages) == 1
        warning = warning_messages[0]
        assert warning.content_type == "WarningError"
        assert warning.content == "non-critical issue"
        assert warning.current_message is not None
        assert warning.current_message.id == trigger.id

        # Emitted after _current_message was cleared, so it threads like an ErrorMessage
        assert warning.parent_id is None

        # ProcessedMessage is still emitted exactly once, and before the WarningMessage
        processed_messages = [m for m in new_messages if isinstance(m, ProcessedMessage)]
        assert len(processed_messages) == 1
        assert new_messages.index(processed_messages[0]) < new_messages.index(warning)

        agent_ref.stop()
        orch_ref.stop()

    def test_runtime_error_sends_error_message(self) -> None:
        """RuntimeError: exactly one ErrorMessage IS stored in the orchestrator."""
        config = BaseConfig(name="orch-runtime-test", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        orch_address = ActorAddressImpl(orch_ref)

        # Start an agent wired to this orchestrator
        agent_ref = _FailingAgent.start(
            config=BaseConfig(name="failing-agent-runtime", role="Agent"),
            orchestrator=orch_address,
        )

        # Give on_start + StartMessage time to propagate
        time.sleep(0.3)

        messages_before = len(orch.messages.get())

        # Send message via tell() — real message delivery path
        trigger = TriggerMessage(error_type="runtime")
        agent_ref.tell(trigger)

        # Allow the actor to process and telemetry to propagate
        time.sleep(0.5)

        # Verify an ErrorMessage WAS recorded
        messages_after = orch.messages.get()
        new_messages = messages_after[messages_before:]
        error_messages = [m for m in new_messages if isinstance(m, ErrorMessage)]
        assert len(error_messages) == 1, (
            f"RuntimeError should produce exactly one ErrorMessage, got {len(error_messages)}"
        )
        assert error_messages[0].content_type == "RuntimeError"
        assert "critical failure" in error_messages[0].content

        agent_ref.stop()
        orch_ref.stop()
