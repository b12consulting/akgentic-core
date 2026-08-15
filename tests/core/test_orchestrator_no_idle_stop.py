"""Tests for the ratified behaviour change: an idle Orchestrator runs indefinitely.

The orchestrator no longer owns an inactivity clock. It never stops itself on
idleness and never signals idleness to anyone — the only stop it announces is
one it has been asked to perform. Idle-stop is an opt-in deployment policy owned
end to end by a subscriber, one layer up.
"""

import os
import time
import uuid
from collections.abc import Generator
from unittest.mock import patch

import pykka
import pytest

from akgentic.core.agent_config import BaseConfig
from akgentic.core.messages.message import Message
from akgentic.core.messages.orchestrator import ProcessedMessage, ReceivedMessage
from akgentic.core.orchestrator import Orchestrator

# The former default inactivity delay, expressed as an env value. Setting it is
# the point of these tests: if core still read it, an idle orchestrator would
# stop itself within a second.
IDLE_ENV_DELAY = "1"

# Twice the env delay above — long enough that a countdown, if one still
# existed, would have fired well before the assertions run.
IDLE_WAIT_SECONDS = 2.5


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


class _RecordingSubscriber:
    """Records every hook the orchestrator could conceivably dispatch.

    ``on_stop_request`` is counted here to prove what does NOT raise it: it is
    the begin-signal of an ``Orchestrator.stop()``, so neither idleness nor a
    raw Pykka ``actor_ref.stop()`` may ever produce one.
    """

    def __init__(self) -> None:
        self.stop_request_count: int = 0
        self.stop_count: int = 0
        self.messages: list[Message] = []

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        """Protocol compliance — no-op for these tests."""
        pass

    def on_stop_request(self, team_id: uuid.UUID) -> None:
        """Teardown begin-signal — asserted never to fire on these paths."""
        self.stop_request_count += 1

    def on_stop(self, team_id: uuid.UUID) -> None:
        self.stop_count += 1

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)


class _AttributeExposingOrchestrator(Orchestrator):
    """Orchestrator subclass exposing its instance attributes to Pykka proxies.

    Pykka's proxy filters out underscore-prefixed members, so a test cannot ask
    a live actor about ``_timer`` directly. This public façade answers the
    question without reaching into the actor's internals — the same pattern as
    ``_NotifyExposingOrchestrator`` in ``tests/core/test_orchestrator.py``.
    """

    def instance_attributes(self) -> list[str]:
        """Public façade over ``vars(self)`` for proxy-driven tests."""
        return sorted(vars(self))


class TestIdleOrchestratorDoesNothing:
    """An idle orchestrator neither stops itself nor notifies its subscribers."""

    def test_idle_orchestrator_neither_stops_nor_notifies(self) -> None:
        """An orchestrator left completely idle stays alive and stays silent.

        ``ORCHESTRATOR_TIMEOUT_DELAY`` is set deliberately: the assertion that
        nothing happens after 2.5s of idleness is simultaneously the proof that
        core no longer reads that variable.
        """
        with patch.dict(os.environ, {"ORCHESTRATOR_TIMEOUT_DELAY": IDLE_ENV_DELAY}):
            config = BaseConfig(name="test-orchestrator", role="Orchestrator")
            orch_ref = Orchestrator.start(config=config)
            orch = orch_ref.proxy()

            sub = _RecordingSubscriber()
            orch.subscribe(sub).get()

            time.sleep(IDLE_WAIT_SECONDS)

            assert orch_ref.is_alive()
            assert sub.stop_request_count == 0
            assert sub.stop_count == 0

            orch_ref.stop()

    def test_idleness_and_a_raw_actor_stop_never_raise_on_stop_request(self) -> None:
        """Over a full lifecycle, neither idleness nor a raw actor stop raises the hook.

        Register, drive both task-boundary handlers through, idle past the
        former delay, then stop through Pykka directly: ``on_message`` and
        ``on_stop`` fire normally while ``on_stop_request`` stays at zero.
        ``actor_ref.stop()`` enqueues ``_ActorStop`` and never enters
        ``Orchestrator.stop()``, which is the only dispatcher of the hook.
        """
        with patch.dict(os.environ, {"ORCHESTRATOR_TIMEOUT_DELAY": IDLE_ENV_DELAY}):
            config = BaseConfig(name="test-orchestrator", role="Orchestrator")
            orch_ref = Orchestrator.start(config=config)
            orch = orch_ref.proxy()

            sub = _RecordingSubscriber()
            orch.subscribe(sub).get()

            dummy_config = BaseConfig(name="dummy-agent", role="Agent")

            class _DummyOrch(Orchestrator):
                pass

            dummy_ref = _DummyOrch.start(config=dummy_config)
            sender_addr = dummy_ref.proxy().myAddress.get()

            received = ReceivedMessage(message_id=uuid.uuid4())
            processed = ProcessedMessage(message_id=uuid.uuid4())
            orch.receiveMsg_ReceivedMessage(received, sender_addr).get()
            orch.receiveMsg_ProcessedMessage(processed, sender_addr).get()

            time.sleep(IDLE_WAIT_SECONDS)

            assert sub.stop_request_count == 0
            assert [type(m) for m in sub.messages] == [ReceivedMessage, ProcessedMessage]

            dummy_ref.stop()
            orch_ref.stop(block=True)

            assert sub.stop_request_count == 0
            assert sub.stop_count == 1


class TestOrchestratorHasNoClock:
    """The orchestrator exposes no timer accessor and holds no timer attribute."""

    def test_orchestrator_has_no_get_timer(self) -> None:
        """``get_timer`` is gone from the class."""
        assert not hasattr(Orchestrator, "get_timer")

    def test_orchestrator_has_no_timer_attribute(self) -> None:
        """A started orchestrator holds no ``_timer`` instance attribute."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = _AttributeExposingOrchestrator.start(config=config)
        orch = orch_ref.proxy()

        attributes = orch.instance_attributes().get()

        assert "_timer" not in attributes
        # The ADR-012 stop backstop is a different timer and must still be there.
        assert "_stop_backstop" in attributes

        orch_ref.stop()
