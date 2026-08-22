"""Behavioural tests for ``Akgent.consume_mailbox`` and its ``HandledMessage`` emission.

The primitive removes named messages from the actor's *own* pykka inbox, so every
test here needs mail sitting in that inbox **unread**: the actor thread must be
parked inside a handler while the test thread enqueues more. ``_ParkingAgent``
provides that park — which is also the precondition ``consume_mailbox``
documents, since a parked actor is the inbox's only consumer and it is not
dequeuing.

``_Probe`` is the only channel between the two threads; the agent instance itself
is never reached into.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import MagicMock

import pykka
import pytest

import akgentic.core
from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message
from akgentic.core.messages.orchestrator import (
    HandledMessage,
    ProcessedMessage,
    ReceivedMessage,
)

# Every wait in this module is a liveness guard, not a timing assumption: the
# events it waits on are set within microseconds on a healthy run.
TIMEOUT = 5.0


class ParkMessage(Message):
    """Message whose handler parks the actor thread so mail queues up behind it."""


class WorkMessage(Message):
    """Ordinary mail — queued behind the park, then either consumed or delivered."""

    content: str = ""


class _Probe:
    """Shared state between the test thread and the parked actor thread."""

    def __init__(self) -> None:
        self.parked = Event()
        self.release = Event()
        self.consume_ids: list[uuid.UUID] = []
        self.consumed: list[Message] = []
        self.mailbox_after: list[Message] = []
        self.delivered: list[WorkMessage] = []


class _ParkingAgent(Akgent[BaseConfig, BaseState]):
    """Agent that blocks inside its ``ParkMessage`` handler until the test releases it.

    On release it calls ``consume_mailbox`` with whatever ids the test staged and
    records the result plus the surviving mailbox — both read from inside the same
    turn, before the actor resumes dequeuing.
    """

    def __init__(self, probe: _Probe, **kwargs: Any) -> None:
        self.probe = probe
        super().__init__(**kwargs)

    def receiveMsg_ParkMessage(self, msg: ParkMessage, sender: Any) -> str:
        self.probe.parked.set()
        self.probe.release.wait(timeout=TIMEOUT)
        self.probe.consumed = self.consume_mailbox(self.probe.consume_ids)
        self.probe.mailbox_after = self.get_mailbox()
        return "parked"

    def receiveMsg_WorkMessage(self, msg: WorkMessage, sender: Any) -> str:
        self.probe.delivered.append(msg)
        return msg.content


def _mock_orchestrator() -> tuple[MagicMock, ActorAddressImpl]:
    """Build a mock orchestrator whose ``tell`` records telemetry in call order."""
    mock_orch_ref = MagicMock()
    mock_orch_ref.is_alive.return_value = True
    return mock_orch_ref, ActorAddressImpl(mock_orch_ref)


def _telemetry(mock_orch_ref: MagicMock) -> list[Message]:
    """Every Message told to the orchestrator, in call order."""
    return [
        arg
        for call in mock_orch_ref.tell.call_args_list
        for arg in call[0]
        if isinstance(arg, Message)
    ]


def _handled_ids(mock_orch_ref: MagicMock) -> list[uuid.UUID]:
    """The ``message_id`` of every HandledMessage emitted, in call order."""
    return [m.message_id for m in _telemetry(mock_orch_ref) if isinstance(m, HandledMessage)]


class _Parked:
    """A started agent already parked inside a ``ParkMessage`` handler."""

    def __init__(
        self,
        ref: pykka.ActorRef[Any],
        probe: _Probe,
        orchestrator: MagicMock,
        park: ParkMessage,
    ) -> None:
        self.ref = ref
        self.probe = probe
        self.orchestrator = orchestrator
        self.park = park

    def queue(self, *contents: str) -> list[WorkMessage]:
        """Tell the parked actor one WorkMessage per content, in order."""
        messages = [WorkMessage(content=content) for content in contents]
        for message in messages:
            self.ref.tell(message)
        return messages

    def release(self, consume_ids: list[uuid.UUID]) -> None:
        """Stage the ids, release the park, and wait for the inbox to settle.

        The trailing ``ask`` is enqueued behind everything the test told the actor,
        so when it answers, the park turn has ended (its ``ProcessedMessage`` is
        out) and every surviving message has had its turn. Its payload is a plain
        string rather than a ``Message``, so it contributes no telemetry of its own.
        """
        self.probe.consume_ids = consume_ids
        self.probe.release.set()
        self.ref.ask("settled", timeout=TIMEOUT)


@pytest.fixture
def parked(request: pytest.FixtureRequest) -> Iterator[_Parked]:
    """Yield an agent confirmed to be inside the park handler.

    Anything told to the ref after this fixture returns is guaranteed to sit
    unread in the inbox, which is what every test below depends on.
    """
    probe = _Probe()
    mock_orch_ref, mock_orch = _mock_orchestrator()
    ref = _ParkingAgent.start(
        probe=probe,
        agent_id=uuid.uuid4(),
        config=BaseConfig(name=f"parking-{request.node.name}", role="Tester"),
        team_id=uuid.uuid4(),
        orchestrator=mock_orch,
    )
    park = ParkMessage()
    ref.tell(park)
    assert probe.parked.wait(timeout=TIMEOUT), "agent never entered the park handler"
    try:
        yield _Parked(ref, probe, mock_orch_ref, park)
    finally:
        probe.release.set()
        pykka.ActorRegistry.stop_all()


class TestConsumeMailboxRemoval:
    """What leaves the mailbox, what stays, and in which order."""

    def test_removes_the_named_message_and_preserves_the_rest(self, parked: _Parked) -> None:
        """Consuming the middle of three leaves [A, C] in order and returns [B] (AC #5)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([b.id])

        assert [m.id for m in parked.probe.consumed] == [b.id]
        assert [m.id for m in parked.probe.mailbox_after] == [a.id, c.id]

    def test_a_consumed_message_never_gets_its_own_turn(self, parked: _Parked) -> None:
        """The removed message is not delivered afterwards — that is the point (AC #4)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([b.id])

        assert [m.id for m in parked.probe.delivered] == [a.id, c.id]

    def test_returns_payloads_in_queue_order_not_argument_order(self, parked: _Parked) -> None:
        """The return is ordered by the queue, whatever order the ids were named in (AC #4)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([c.id, a.id])

        assert [m.id for m in parked.probe.consumed] == [a.id, c.id]
        assert [m.id for m in parked.probe.mailbox_after] == [b.id]

    def test_consuming_every_queued_message_empties_the_mailbox(self, parked: _Parked) -> None:
        """A call naming all queued ids removes them all (AC #4)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([a.id, b.id, c.id])

        assert [m.id for m in parked.probe.consumed] == [a.id, b.id, c.id]
        assert parked.probe.mailbox_after == []
        assert parked.probe.delivered == []


class TestConsumeMailboxUnknownIds:
    """Ids that are not (or no longer) queued are a silent no-op."""

    def test_unknown_id_removes_nothing_and_emits_nothing(self, parked: _Parked) -> None:
        """An id that was never queued changes neither the mailbox nor telemetry (AC #6)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([uuid.uuid4()])

        assert parked.probe.consumed == []
        assert [m.id for m in parked.probe.mailbox_after] == [a.id, b.id, c.id]
        assert _handled_ids(parked.orchestrator) == []

    def test_empty_id_list_is_a_no_op(self, parked: _Parked) -> None:
        """Consuming nothing removes nothing and emits nothing (AC #6)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([])

        assert parked.probe.consumed == []
        assert [m.id for m in parked.probe.mailbox_after] == [a.id, b.id, c.id]
        assert _handled_ids(parked.orchestrator) == []

    def test_mixed_call_removes_and_reports_only_what_was_present(self, parked: _Parked) -> None:
        """A known id alongside an unknown one removes and reports just the known (AC #6)."""
        a, b, c = parked.queue("a", "b", "c")

        parked.release([b.id, uuid.uuid4()])

        assert [m.id for m in parked.probe.consumed] == [b.id]
        assert [m.id for m in parked.probe.mailbox_after] == [a.id, c.id]
        assert _handled_ids(parked.orchestrator) == [b.id]


class TestHandledMessageEmission:
    """The primitive owns the emission — one HandledMessage per removal."""

    def test_one_handled_message_per_removed_message(self, parked: _Parked) -> None:
        """Two removals emit exactly two HandledMessages, naming the removed ids (AC #7)."""
        a, _b, c = parked.queue("a", "b", "c")

        parked.release([a.id, c.id])

        assert _handled_ids(parked.orchestrator) == [a.id, c.id]

    def test_emission_nests_inside_the_callers_turn(self, parked: _Parked) -> None:
        """The HandledMessage lands between the caller turn's Received and Processed (AC #8).

        Its ``parent_id`` is the triggering message's id — a consequence of
        ``_notify_orchestrator`` stamping ``_current_message`` onto every emission,
        asserted here rather than re-implemented.
        """
        _a, b, _c = parked.queue("a", "b", "c")

        parked.release([b.id])

        telemetry = _telemetry(parked.orchestrator)
        received = next(
            i
            for i, m in enumerate(telemetry)
            if isinstance(m, ReceivedMessage) and m.message_id == parked.park.id
        )
        processed = next(
            i
            for i, m in enumerate(telemetry)
            if isinstance(m, ProcessedMessage) and m.message_id == parked.park.id
        )
        handled = next(i for i, m in enumerate(telemetry) if isinstance(m, HandledMessage))

        assert received < handled < processed
        assert telemetry[handled].parent_id == parked.park.id

    def test_absorbed_mail_gets_no_received_or_processed_pair(self, parked: _Parked) -> None:
        """A consumed message is never reported as having had a turn (AC #7).

        Forging the Received/Processed pair for absorbed mail is the alternative
        ADR-019 rejects: it would claim a turn that never happened and leave the two
        most load-bearing telemetry types ambiguous forever.
        """
        _a, b, _c = parked.queue("a", "b", "c")

        parked.release([b.id])

        turn_ids = [
            m.message_id
            for m in _telemetry(parked.orchestrator)
            if isinstance(m, ReceivedMessage | ProcessedMessage)
        ]
        assert b.id not in turn_ids


def test_akgentic_core_never_calls_the_primitive() -> None:
    """NFR1: core ships ``consume_mailbox`` but calls it from nowhere.

    The callers live in akgentic-agent and akgentic-tool. A call introduced inside
    core would change the mailbox semantics of every existing agent, which is
    exactly what "no behaviour change without a caller" rules out.

    Call sites are matched through the AST rather than by text, so docstrings and
    comments naming the primitive do not trip this.
    """
    src_root = Path(akgentic.core.__file__).parent
    offenders: list[str] = []
    definitions: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name == "consume_mailbox":
                definitions.append(f"{path.relative_to(src_root)}:{node.lineno}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "consume_mailbox"
            ):
                offenders.append(f"{path.relative_to(src_root)}:{node.lineno}")

    # Finding the definition proves the walk reached the tree that owns the
    # primitive. Without it an empty walk — a wrong src_root, a checkout whose
    # akgentic.core resolves elsewhere — satisfies the assertion below vacuously.
    assert definitions, f"walked the wrong tree: no consume_mailbox defined under {src_root}"
    assert offenders == [], f"akgentic-core must not call consume_mailbox (NFR1): {offenders}"
