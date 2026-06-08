"""Behaviour tests for the non-blocking orchestrator stop (ADR-012).

Ports the deterministic reproduction from
``packages/akgentic-team/research/test_stop_during_processing_deadlock.py`` into
the CI suite (reusing its ``RecordingSubscriber`` / ``DeadlockWorker`` /
``TelemetryWorker`` / ``_build_team`` harness) and adds the behaviour matrix from
the story Testing section.

All assertions are behaviour-only — no ADR-reference-string checks (Golden
Rule #8). Uses ONLY ``akgentic-core`` primitives (no LLM / infra / TestModel).
"""

from __future__ import annotations

import gc
import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import Generator

import pykka
import pytest

from akgentic.core.actor_address import ActorAddress
from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.messages.message import Message, UserMessage
from akgentic.core.orchestrator import Orchestrator

# Signals the moment a worker is INSIDE its message handler (actor busy).
_in_handler = threading.Event()

# How long a worker holds its handler open so the stop request arrives while busy.
_HANDLER_HOLD_S = 0.5


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Stop any leaked actors after each test so failures don't cascade."""
    yield
    pykka.ActorRegistry.stop_all()


class RecordingSubscriber:
    """Captures the orchestrator's ``on_message`` telemetry fan-out so a test can
    observe which messages it records and forwards to subscribers."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)

    # Lifecycle hooks — no-ops, present to satisfy the EventSubscriber protocol.
    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        ...

    def on_stop_request(self, team_id: uuid.UUID) -> None:
        ...

    def on_stop(self, team_id: uuid.UUID) -> None:
        ...

    def type_counts(self) -> Counter[str]:
        return Counter(m.__class__.__name__ for m in self.messages)


class DeadlockWorker(Akgent):
    """Mid-message, re-enters the orchestrator via ``get_team()`` — the reentrant
    edge. Mirrors ``BaseAgent._build_structured_output_type()``."""

    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:
        _in_handler.set()
        time.sleep(_HANDLER_HOLD_S)
        # Blocking ask back to the orchestrator. With a non-blocking orchestrator
        # stop this always resolves; with the legacy blocking stop it deadlocks.
        self.get_team()


class TelemetryWorker(Akgent):
    """Mid-message, does NOT touch the orchestrator — no deadlock. Emits its final
    ``ProcessedMessage`` when the handler returns, as it is being stopped."""

    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:
        _in_handler.set()
        time.sleep(_HANDLER_HOLD_S)


class WedgedWorker(Akgent):
    """Never stops gracefully — overrides ``stop()`` to ignore the request so the
    orchestrator's roster never empties on its own (exercises the backstop)."""

    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:
        _in_handler.set()

    def stop(self) -> None:  # type: ignore[override]
        # Swallow the stop: the actor keeps running, so its StopMessage never
        # lands and get_team() never empties — only the backstop can finalize.
        return None


def _build_team(
    system: ActorSystem, worker_cls: type[Akgent]
) -> tuple[ActorAddress, ActorAddress, RecordingSubscriber]:
    """Start an orchestrator + one child worker under it; return (orch, child, recorder)."""
    _in_handler.clear()
    orch_addr = system.createActor(
        Orchestrator,
        config=BaseConfig(name="@Orchestrator", role="Orchestrator"),
    )
    orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
    recorder = RecordingSubscriber()
    orch_proxy.subscribe(recorder)
    child_addr = orch_proxy.createActor(
        worker_cls, config=BaseConfig(name="@Worker", role="Worker")
    )
    assert child_addr is not None
    return orch_addr, child_addr, recorder


# ---------------------------------------------------------------------------
# Ported reproduction (the two research tests, asserting the FIXED behaviour)
# ---------------------------------------------------------------------------


def test_stop_during_processing_does_not_deadlock() -> None:
    """DeadlockWorker calls get_team() mid-message; stop() is asked at that moment.

    The returned event must be set within the test watchdog (no deadlock) and the
    team must tear down. WATCHDOG bounds the *test*; GRACE is the backstop passed
    to stop().
    """
    grace = 5.0
    watchdog = 10.0
    system = ActorSystem()
    orch_addr, child_addr, _ = _build_team(system, DeadlockWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0), "worker never entered its handler"

    event: threading.Event = system.proxy_ask(orch_addr, Orchestrator).stop(grace)
    assert event.wait(timeout=watchdog), "orchestrator.stop() deadlocked (event never set)"
    assert not orch_addr.is_alive()


def _processed_count_after_worker_stop(system: ActorSystem) -> int:
    """Stop a TelemetryWorker while its message is in flight, then GC it, and
    return how many ProcessedMessages the (still-alive) orchestrator recorded.

    Stopping only the worker (blocking child stop) keeps the orchestrator alive
    so we can query its history. The orchestrator's GC-safe identity guard
    (ADR-012 §5) must not throw when it drains the late ProcessedMessage from the
    now-collected worker — otherwise the message is dropped (research §3.1).
    """
    orch_addr, child_addr, _ = _build_team(system, TelemetryWorker)
    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0), "worker never entered its handler"

    # Blocking stop of the worker only (no deadlock: TelemetryWorker never
    # re-enters the orchestrator). The worker emits its ProcessedMessage right as
    # it is torn down.
    system.proxy_ask(child_addr, Akgent).stop()
    del child_addr
    gc.collect()  # promptly collect the stopped worker, surfacing the §3.1 race
    time.sleep(0.3)  # let the orchestrator drain the queued ProcessedMessage

    from akgentic.core.messages.orchestrator import ProcessedMessage

    recorded = system.proxy_ask(orch_addr, Orchestrator).get_messages(
        message_type=ProcessedMessage
    )
    return len(recorded)


def test_processed_telemetry_survives_agent_stop() -> None:
    """Every in-flight message's ProcessedMessage is recorded even when the
    emitting agent is stopped + GC'd right after (GC-safe identity — research §3.1).

    Loops N=25 because the loss was a GC race; the orchestrator must record the
    ProcessedMessage on EVERY run.
    """
    runs = 25
    losses: list[int] = []
    for i in range(runs):
        system = ActorSystem()
        if _processed_count_after_worker_stop(system) < 1:
            losses.append(i)

    assert not losses, f"ProcessedMessage telemetry LOST in {len(losses)}/{runs} runs ({losses})"


# ---------------------------------------------------------------------------
# Behaviour matrix
# ---------------------------------------------------------------------------


def test_stop_returns_event_immediately() -> None:
    """stop() returns a threading.Event, unset on return, with the orchestrator
    thread free (a concurrent get_team() ask resolves before the event is set)."""
    system = ActorSystem()
    orch_addr, child_addr, _ = _build_team(system, DeadlockWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0)

    event = system.proxy_ask(orch_addr, Orchestrator).stop(5.0)
    assert isinstance(event, threading.Event)
    assert not event.is_set()  # returned before teardown completed

    # The orchestrator thread is free: a reentrant ask resolves while draining.
    roster = system.proxy_ask(orch_addr, Orchestrator).get_team()
    assert isinstance(roster, list)

    assert event.wait(timeout=10.0)


def test_stop_is_idempotent() -> None:
    """Two stop() calls return the SAME event; children are told once."""
    system = ActorSystem()
    orch_addr, child_addr, _ = _build_team(system, TelemetryWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0)

    proxy = system.proxy_ask(orch_addr, Orchestrator)
    first = proxy.stop(5.0)
    second = proxy.stop(5.0)
    assert first is second

    assert first.wait(timeout=10.0)


def test_zero_children_team_finalizes() -> None:
    """An orchestrator with no agents sets the event promptly."""
    system = ActorSystem()
    orch_addr = system.createActor(
        Orchestrator, config=BaseConfig(name="@Orchestrator", role="Orchestrator")
    )

    event = system.proxy_ask(orch_addr, Orchestrator).stop(5.0)
    assert event.wait(timeout=5.0)
    assert not orch_addr.is_alive()


def test_backstop_timeout_forces_finalize(caplog: pytest.LogCaptureFixture) -> None:
    """A wedged child that never stops → with a small grace_timeout the backstop
    fires → the event is set within ~grace_timeout, with a WARNING logged."""
    system = ActorSystem()
    orch_addr, child_addr, _ = _build_team(system, WedgedWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0)
    time.sleep(_HANDLER_HOLD_S + 0.1)  # let the handler finish so child is idle but alive

    grace = 1.0
    with caplog.at_level(logging.WARNING):
        event = system.proxy_ask(orch_addr, Orchestrator).stop(grace)
        # Event must NOT set before the grace period (child is wedged).
        assert not event.wait(timeout=0.3)
        # But the backstop sets it within ~grace.
        assert event.wait(timeout=grace + 5.0)

    assert any("forcing teardown" in rec.message for rec in caplog.records)


def test_get_team_safe_after_member_gc() -> None:
    """With a stopped+GC'd member recorded in messages, get_team() (driven during
    _stopping) returns the correct roster and raises no RuntimeError.

    The orchestrator's teardown completion check calls get_team() over every
    Start/Stop sender, including senders whose actor has already been collected.
    A clean event-set proves the completion check did not throw mid-teardown.
    """
    system = ActorSystem()
    orch_addr, child_addr, _ = _build_team(system, TelemetryWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0)
    time.sleep(_HANDLER_HOLD_S + 0.1)

    # Drop our reference so the member can be collected as teardown drains.
    del child_addr
    gc.collect()

    event = system.proxy_ask(orch_addr, Orchestrator).stop(5.0)
    assert event.wait(timeout=10.0)
    assert not orch_addr.is_alive()


def test_actor_address_identity_survives_gc() -> None:
    """After the actor is collected, agent_id / role / __eq__ / __hash__ still
    work; name / serialize() behave as documented (live-resolving)."""
    system = ActorSystem()
    orch_addr = system.createActor(
        Orchestrator, config=BaseConfig(name="@Orchestrator", role="Orchestrator")
    )
    addr = system.createActor(
        Akgent, config=BaseConfig(name="@Solo", role="Worker"), team_id=orch_addr.team_id
    )
    impl = ActorAddressImpl(addr._actor_ref)  # type: ignore[attr-defined]
    twin = ActorAddressImpl(addr._actor_ref)  # type: ignore[attr-defined]

    cached_id = impl.agent_id
    cached_role = impl.role

    # Stop + collect the underlying actor.
    addr._actor_ref.stop(block=True)  # type: ignore[attr-defined]
    del addr
    gc.collect()

    # Cached identity survives GC.
    assert impl.agent_id == cached_id
    assert impl.role == cached_role
    assert impl == twin  # __eq__ works post-GC (reads cached agent_id)
    assert hash(impl) == hash(cached_id)

    # name / serialize() remain live-resolving → raise on a collected actor.
    with pytest.raises(RuntimeError):
        _ = impl.name
    with pytest.raises(RuntimeError):
        _ = impl.serialize()


def test_agent_stop_still_blocking() -> None:
    """A non-orchestrator Akgent.stop() returns None and blocks until children
    are down (asymmetry regression guard)."""
    system = ActorSystem()
    orch_addr = system.createActor(
        Orchestrator, config=BaseConfig(name="@Orchestrator", role="Orchestrator")
    )
    orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
    parent = orch_proxy.createActor(Akgent, config=BaseConfig(name="@Parent", role="Worker"))
    child = system.proxy_ask(parent, Akgent).createActor(
        Akgent, config=BaseConfig(name="@Child", role="Worker")
    )

    result = system.proxy_ask(parent, Akgent).stop()
    assert result is None
    # Blocking stop means the subtree is down on the next line.
    assert not parent.is_alive()
    assert not child.is_alive()


def test_stop_events_suppressed_from_subscribers_during_teardown() -> None:
    """During _stopping, StopMessages are appended to messages but NOT delivered
    to subscribers."""
    system = ActorSystem()
    orch_addr, child_addr, recorder = _build_team(system, TelemetryWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0)

    system.proxy_ask(orch_addr, Orchestrator).stop(5.0).wait()

    # No StopMessage should have reached the subscriber (suppressed during teardown).
    assert recorder.type_counts()["StopMessage"] == 0


def test_shutdown_waits_on_orchestrator_events() -> None:
    """ActorSystem.shutdown() returns only after every orchestrator's event is set;
    no force-kill needed on the happy path."""
    system = ActorSystem()
    orch_addr, child_addr, _ = _build_team(system, TelemetryWorker)

    system.tell(child_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0)

    system.shutdown(timeout=10)

    # shutdown returned → every orchestrator finalized.
    assert not orch_addr.is_alive()
    assert len(system.orchestrators) == 0
