"""Tests for ``TeamStoppingEvent`` — the announcement that a teardown has begun,
and the one place it must NOT reappear: the restore replay.

Without the event a stopped team is byte-for-byte indistinguishable from a quiet
running one: nothing is published when ``Orchestrator.stop()`` starts, so an
out-of-process observer has no way to tell the difference. The event rides the
existing ``EventMessage`` fan-out, so no subscriber has to change to see it.

The ordering of the emission is pinned by orchestrator state observed AT dispatch
time, not by wall-clock luck: ``_stop_non_tool_children()`` uses fire-and-forget
tells, so a child recording its own stop into a shared list would race the
orchestrator's thread and the test would be flaky-GREEN — it would keep passing
with the emission in the wrong place. ``_stopping``, ``_stop_backstop`` and
``_pending_tool_stops`` are all set synchronously on the actor thread.

The second half of the module covers ``restore_message()``. Replay is not
in-memory bookkeeping: its last statement dispatches to every subscriber, on the
same path live telemetry takes, and the community-tier stream subscriber
deliberately does not suppress during restore. So a replayed announcement tells
every client that the team it has just brought back to life is stopped. The skip
keys on the payload carried by ``EventMessage``, never on the envelope — the
envelope carries every domain event, ``ClosedNotification`` included.

Deliberately a NEW module: ``test_orchestrator_stop.py`` holds the non-blocking
stop harness, ``test_orchestrator_stop_request.py`` the lifecycle-hook harness,
and ``test_orchestrator.py::TestRestoreMessage`` the ordinary-replay harness; all
three must stay untouched.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Generator
from typing import Any, override

import pykka
import pytest

from akgentic.core.actor_address import ActorAddress
from akgentic.core.actor_address_impl import ActorAddressProxy
from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.messages.message import Message, UserMessage
from akgentic.core.messages.orchestrator import (
    ClosedNotification,
    EventMessage,
    ProcessedMessage,
    ReceivedMessage,
    SentMessage,
    StartMessage,
    StopMessage,
    TeamStoppingEvent,
)
from akgentic.core.orchestrator import Orchestrator
from akgentic.core.utils.deserializer import ActorAddressDict

# Signals the moment the worker is INSIDE its handler, so the stop below arrives
# while the team is genuinely busy and the roster cannot empty instantly.
_in_handler = threading.Event()

# How long the worker holds its handler open once the stop has been requested.
_HANDLER_HOLD_S = 0.5

# Backstop grace passed to stop(); the watchdog bounds the TEST, not the stop.
_GRACE_S = 5.0
_WATCHDOG_S = 10.0

# One record per dispatch — message-bearing and lifecycle alike, in ONE list so
# their relative order is a fact rather than an inference across two lists:
# (label, _stopping, backstop armed, len(_pending_tool_stops)). Module-level
# because the interesting records are written while the orchestrator is tearing
# itself down — by the time a test can ask, the actor is gone.
DispatchRecord = tuple[str, bool, bool, int]
_dispatch_records: list[DispatchRecord] = []


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Reset the shared observation state and stop leaked actors after each test."""
    _dispatch_records.clear()
    _in_handler.clear()
    yield
    pykka.ActorRegistry.stop_all()


class _BusyWorker(Akgent):
    """A non-tool worker that holds its handler open across the stop request."""

    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:
        _in_handler.set()
        time.sleep(_HANDLER_HOLD_S)


class _ToolActor(Akgent):
    """A ``#``-prefixed tool actor — deferred to phase 2 of the stop sequence."""


def _label(message: Message) -> str:
    """Name a message dispatch by its payload when it is an event, else by its type.

    ``EventMessage`` is the shared carrier for every domain-event payload, so its
    own class name would not distinguish a teardown announcement from any other
    event the team emits.
    """
    if isinstance(message, EventMessage):
        return type(message.event).__name__
    return type(message).__name__


class _ProbeOrchestrator(Orchestrator):
    """Records the orchestrator state visible at every dispatch, of either kind.

    Both overrides run on the actor thread, inside the very call they observe, so
    each record is a synchronous snapshot of how far ``stop()`` has progressed.
    """

    @override
    def _notify_subscribers_message(self, event_method: str, message: Message) -> None:
        _dispatch_records.append(self._snapshot(_label(message)))
        super()._notify_subscribers_message(event_method, message)

    @override
    def _notify_subscribers_lifecycle(
        self,
        event_method: str,
        team_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        _dispatch_records.append(self._snapshot(event_method))
        super()._notify_subscribers_lifecycle(event_method, team_id, **kwargs)

    def _snapshot(self, label: str) -> DispatchRecord:
        """Capture how far the stop sequence has progressed, synchronously."""
        return (
            label,
            self._stopping,
            self._stop_backstop is not None,
            len(self._pending_tool_stops),
        )


class _EventRecordingSubscriber:
    """Records every message it is handed, with no knowledge of any payload type.

    This is also the AC for an unmodified subscriber: it treats a teardown
    announcement as an ordinary ``EventMessage`` and does nothing special.
    """

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)


class _PayloadInspectingSubscriber:
    """A subscriber predating the type that inspects payloads it does not know.

    Reads attributes off whatever ``EventMessage`` carries, the way a subscriber
    written against ``ClosedNotification`` alone would. A fieldless payload must
    not make it raise.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    def on_message(self, msg: Message) -> None:
        if isinstance(msg, EventMessage):
            self.seen.append(type(msg.event).__name__)
            getattr(msg.event, "message_id", None)


def _build_busy_team(
    system: ActorSystem, orchestrator_cls: type[Orchestrator] = Orchestrator
) -> tuple[ActorAddress, ActorAddress]:
    """Start an orchestrator with one ``#`` tool actor and one busy ``@`` worker.

    The tool actor is what keeps ``_pending_tool_stops`` non-empty for the rest
    of ``stop()``, making "phase 1 has not run yet" a synchronously observable
    fact; the busy worker keeps the roster non-empty while it holds its handler.
    """
    orch_addr = system.createActor(
        orchestrator_cls,
        config=BaseConfig(name="@Orchestrator", role="Orchestrator"),
    )
    orch_proxy = system.proxy_ask(orch_addr, orchestrator_cls)
    orch_proxy.createActor(_ToolActor, config=BaseConfig(name="#Tool", role="Tool"))
    worker_addr = orch_proxy.createActor(
        _BusyWorker, config=BaseConfig(name="@Worker", role="Worker")
    )
    assert worker_addr is not None
    return orch_addr, worker_addr


def _occupy_worker(system: ActorSystem, worker_addr: ActorAddress) -> None:
    """Put the worker inside its handler and wait until it is genuinely there."""
    system.tell(worker_addr, UserMessage(content="hello"))
    assert _in_handler.wait(timeout=5.0), "worker never entered its handler"


def _is_announcement(message: Message) -> bool:
    """Whether a message is an ``EventMessage`` carrying a teardown announcement.

    The pair of checks is the point: ``EventMessage`` is the shared carrier for
    every domain-event payload, so only the inner ``.event`` identifies a
    teardown.
    """
    return isinstance(message, EventMessage) and isinstance(message.event, TeamStoppingEvent)


def _stopping_events(subscriber: _EventRecordingSubscriber) -> list[Message]:
    """The teardown announcements among everything the subscriber was handed."""
    return [msg for msg in subscriber.messages if _is_announcement(msg)]


def _error_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The ERROR-and-above records only — what "logs no error" actually means.

    ``caplog.records`` accumulates across the whole test, including the team
    setup that runs OUTSIDE the ``at_level`` block, so asserting the capture is
    entirely empty would turn red on any unrelated WARNING logged during setup —
    a failure about something these tests never claimed.
    """
    return [record.message for record in caplog.records if record.levelno >= logging.ERROR]


def _proxy_address(name: str, team_id: uuid.UUID) -> ActorAddress:
    """A snapshot address, the only kind a replayed log ever carries.

    A persisted message's sender was serialized when it was stored, so what
    ``restore_message`` is handed back is always an ``ActorAddressProxy``, never
    a live actor reference.
    """
    address: ActorAddressDict = {
        "__actor_address__": True,
        "__actor_type__": "akgentic.core.actor_address_impl.ActorAddressProxy",
        "agent_id": str(uuid.uuid4()),
        "name": name,
        "role": "Worker",
        "team_id": str(team_id),
        "squad_id": "",
        "is_user_proxy": False,
    }
    return ActorAddressProxy(address)


def _orchestrator_with_recorder(
    system: ActorSystem,
) -> tuple[Orchestrator, _EventRecordingSubscriber]:
    """A bare orchestrator proxy with a recorder already attached to its fan-out."""
    orch_addr = system.createActor(
        Orchestrator, config=BaseConfig(name="@Orchestrator", role="Orchestrator")
    )
    orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
    recorder = _EventRecordingSubscriber()
    orch_proxy.subscribe(recorder)
    return orch_proxy, recorder


def _every_message_kind(worker: ActorAddress, team_id: uuid.UUID) -> list[Message]:
    """One ordered log covering every kind a replay can carry, announcement last.

    Asserted as a whole rather than as seven single-message replays, so the test
    pins relative ORDER as well as membership.

    The ``StartMessage`` and ``StopMessage`` are stamped with a sender the way
    ``emitMessage`` stamps one: ``get_team()`` skips senderless messages outright,
    so an unstamped pair would make any roster assertion pass vacuously.
    """
    start = StartMessage(config=BaseConfig(name="@Worker", role="Worker"))
    start.init(worker, team_id)
    stop = StopMessage()
    stop.init(worker, team_id)
    return [
        start,
        stop,
        SentMessage(message=UserMessage(content="x"), recipient=worker),
        ReceivedMessage(message_id=uuid.uuid4()),
        ProcessedMessage(message_id=uuid.uuid4()),
        EventMessage(event=ClosedNotification(message_id=uuid.uuid4())),
        EventMessage(event=TeamStoppingEvent()),
    ]


def _ids(messages: list[Message]) -> list[uuid.UUID]:
    """Identify messages by ``id``, not by object identity.

    ``_notify_subscribers_message`` hands subscribers a snapshot rather than the
    object it was given, so ``is`` comparisons against the replayed input are not
    reliable; ``id`` survives snapshotting unchanged.
    """
    return [message.id for message in messages]


class TestTheEventIsPublished:
    """Stopping a team puts exactly one announcement on the wire."""

    def test_a_stop_publishes_one_correctly_addressed_event(self) -> None:
        """One event, carrying the stopping team's id and the orchestrator as sender.

        ``Orchestrator.stop()`` is the single entry point the REST stop path and
        the idle-stop path both converge on, so this one assertion covers both
        causes of a teardown — a separate idle-stop case would assert nothing new.

        The subscriber is handed a SNAPSHOT (``snapshot_for_subscribers`` replaces
        every live ``ActorAddressImpl`` with an ``ActorAddressProxy``), so the
        sender is compared by ``agent_id``, never by object identity.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        subscriber = _EventRecordingSubscriber()
        orch_proxy.subscribe(subscriber)
        team_id: uuid.UUID = orch_proxy.team_id

        _occupy_worker(system, worker_addr)
        event: threading.Event = orch_proxy.stop(_GRACE_S)
        assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        announcements = _stopping_events(subscriber)
        assert len(announcements) == 1
        assert announcements[0].team_id == team_id
        assert announcements[0].sender is not None
        assert announcements[0].sender.agent_id == orch_addr.agent_id

    def test_a_second_stop_publishes_nothing_further(self) -> None:
        """Two ``stop()`` calls share one event and announce the teardown exactly once.

        Idempotency is INHERITED from the early-return that already guards
        ``stop()``; there is no announcement flag of its own to get out of step.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        subscriber = _EventRecordingSubscriber()
        orch_proxy.subscribe(subscriber)

        _occupy_worker(system, worker_addr)
        first: threading.Event = orch_proxy.stop(_GRACE_S)
        second: threading.Event = orch_proxy.stop(_GRACE_S)

        assert first is second
        assert first.wait(timeout=_WATCHDOG_S), "stop never completed"
        assert len(_stopping_events(subscriber)) == 1

    def test_a_zero_agent_team_still_announces(self) -> None:
        """A team with no members announces before it finalizes.

        ``stop()`` reaches ``_finalize_stop()`` synchronously inside the same call
        here — nothing will ever report a ``StopMessage`` — which makes this the
        tightest ordering case in the codebase.
        """
        system = ActorSystem()
        orch_addr = system.createActor(
            Orchestrator, config=BaseConfig(name="@Orchestrator", role="Orchestrator")
        )
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        subscriber = _EventRecordingSubscriber()
        orch_proxy.subscribe(subscriber)
        assert orch_proxy.get_team() == [], "the team was expected to have no members"

        event: threading.Event = orch_proxy.stop(_GRACE_S)
        assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert len(_stopping_events(subscriber)) == 1


class TestTheEventPrecedesEveryTeardownStep:
    """The announcement goes out before the stop path has done anything at all."""

    def test_the_event_precedes_the_lifecycle_hook_and_all_teardown_work(self) -> None:
        """It is dispatched first, with ``stop()`` untouched at that moment.

        The ordered record is the primary pin, and it alone is sufficient today:
        ``on_stop_request`` is dispatched immediately below the emission, so ANY
        downward move of the emission reddens the index assertion. The state
        snapshot is NOT an independent second mutation — ``self._stopping = True``
        sits *below* the ``on_stop_request`` dispatch, so sinking past the flag
        necessarily sinks past the hook and both assertions fire together. It is
        kept as a positional guard: it pins the emission against the teardown
        work itself rather than against a hook whose own position could later
        move, and it is what would still fail if ``on_stop_request`` were
        relocated out from under the ordering assertion.

        The three state assertions are not equally strong. ``stopping`` is the
        durable one — set once and never cleared, so it rejects every position
        below the flag. ``backstop_armed`` is monotonic too. ``pending_tools``
        is NOT: ``_maybe_stop_pending_tools()`` empties the list again, so a
        zero there proves "phase 1 has not run" only for a position above that
        call, and it must not be read as a general guard.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system, _ProbeOrchestrator)
        orch_proxy = system.proxy_ask(orch_addr, _ProbeOrchestrator)

        _occupy_worker(system, worker_addr)
        event: threading.Event = orch_proxy.stop(_GRACE_S)
        assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        labels = [record[0] for record in _dispatch_records]
        assert labels.count("TeamStoppingEvent") == 1, "the teardown was announced twice"
        assert labels.index("TeamStoppingEvent") < labels.index("on_stop_request"), (
            "dispatched after the on_stop_request hook"
        )

        announcement = _dispatch_records[labels.index("TeamStoppingEvent")]
        _, stopping, backstop_armed, pending_tools = announcement
        assert stopping is False, "emitted after self._stopping was set"
        assert backstop_armed is False, "emitted after the backstop was armed"
        assert pending_tools == 0, "emitted after phase 1 stopped the non-tool children"


class TestSubscribersThatNeverHeardOfTheType:
    """An unmodified subscriber takes the new payload in its stride."""

    def test_a_payload_inspecting_subscriber_is_unharmed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It receives an ordinary ``EventMessage``, raises nothing, logs no ERROR.

        Nothing had to be taught about ``TeamStoppingEvent`` for it to arrive:
        the event rides the ``on_message`` fan-out every subscriber already has.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        subscriber = _PayloadInspectingSubscriber()
        orch_proxy.subscribe(subscriber)

        _occupy_worker(system, worker_addr)
        with caplog.at_level(logging.ERROR):
            event: threading.Event = orch_proxy.stop(_GRACE_S)
            assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert subscriber.seen.count("TeamStoppingEvent") == 1
        assert _error_messages(caplog) == []


class TestRestoreSkipsTheAnnouncement:
    """A restore replay leaves the previous lifecycle's teardown out entirely."""

    def test_a_replayed_announcement_reaches_neither_history_nor_subscribers(self) -> None:
        """Both halves of ``restore_message`` are skipped, not just the append.

        The subscriber assertion is the one that matters: ``restore_message``
        ends in ``_notify_subscribers_message``, so a skip that dropped only the
        ``self.messages`` append would leave the fan-out intact and every client
        would still be told its freshly restored team is stopped.
        """
        system = ActorSystem()
        orch_proxy, recorder = _orchestrator_with_recorder(system)

        announcement = EventMessage(event=TeamStoppingEvent())
        orch_proxy.restore_message(announcement)

        assert recorder.messages == []
        assert orch_proxy.get_events(event_class=TeamStoppingEvent) == []
        assert announcement.id not in _ids(orch_proxy.get_messages())

    def test_every_other_message_in_the_same_log_replays_unchanged(self) -> None:
        """One log of every kind: all of it replays, in order, minus the announcement.

        ``get_messages()`` is never empty to begin with — ``on_start()`` records
        the orchestrator's own ``StartMessage`` before any test can touch it — so
        history is asserted over the replayed ids alone, and the subscriber
        record carries the strict whole-sequence assertion.
        """
        system = ActorSystem()
        orch_proxy, recorder = _orchestrator_with_recorder(system)
        team_id: uuid.UUID = orch_proxy.team_id
        worker = _proxy_address("@Worker", team_id)

        log = _every_message_kind(worker, team_id)
        for message in log:
            orch_proxy.restore_message(message)

        expected = _ids([message for message in log if not _is_announcement(message)])
        assert len(expected) == len(log) - 1
        assert _ids(recorder.messages) == expected

        replayed_ids = set(_ids(log))
        history = [msg for msg in orch_proxy.get_messages() if msg.id in replayed_ids]
        assert _ids(history) == expected

    def test_an_event_carrying_another_payload_replays_normally(self) -> None:
        """A ``ClosedNotification`` — the dismissal the frontend replays — is untouched.

        This is the test that pins the guard to the inner payload.
        ``EventMessage`` is the shared carrier for every domain event, so a guard
        broadened to ``isinstance(message, EventMessage)`` alone would silently
        drop every dismissal a client folds into its notification state on
        restore, along with any payload added later. Do not "simplify" this test
        by dropping the ``ClosedNotification``: it is the whole subject.
        """
        system = ActorSystem()
        orch_proxy, recorder = _orchestrator_with_recorder(system)

        dismissal = EventMessage(event=ClosedNotification(message_id=uuid.uuid4()))
        orch_proxy.restore_message(dismissal)

        assert _ids(recorder.messages) == [dismissal.id]
        assert _ids(orch_proxy.get_events(event_class=ClosedNotification)) == [dismissal.id]

    def test_the_roster_is_unaffected_by_the_skip(self) -> None:
        """The same log with and without the announcement yields the same roster.

        The early return also skips ``self._current_team_members = None``. That is
        correct rather than an oversight — ``get_team()`` derives the roster from
        ``StartMessage``/``StopMessage`` senders alone, so an ``EventMessage``
        never contributed to it and nothing it reads changed. This is the guard
        that keeps that true if the return ever grows a body.
        """
        system = ActorSystem()
        with_skip, _ = _orchestrator_with_recorder(system)
        without_skip, _ = _orchestrator_with_recorder(system)
        team_id: uuid.UUID = with_skip.team_id

        kept = _proxy_address("@Kept", team_id)
        gone = _proxy_address("@Gone", team_id)
        kept_start = StartMessage(config=BaseConfig(name="@Kept", role="Worker"))
        kept_start.init(kept, team_id)
        gone_start = StartMessage(config=BaseConfig(name="@Gone", role="Worker"))
        gone_start.init(gone, team_id)
        gone_stop = StopMessage()
        gone_stop.init(gone, team_id)
        announcement = EventMessage(event=TeamStoppingEvent())

        for message in [kept_start, gone_start, announcement, gone_stop]:
            with_skip.restore_message(message)
        for message in [kept_start, gone_start, gone_stop]:
            without_skip.restore_message(message)

        roster = {member.agent_id for member in with_skip.get_team()}
        assert roster == {kept.agent_id}
        assert roster == {member.agent_id for member in without_skip.get_team()}


class TestTheStopThenRestoreCycleIsClean:
    """The end-to-end form: a real teardown's log, replayed into a new team."""

    def test_a_captured_teardown_log_restores_without_the_announcement(self) -> None:
        """Stop a real team, replay what a persistence subscriber stored, see no teardown.

        The log cannot be read off the stopped orchestrator — once ``stop()``
        completes the actor is gone and ``get_messages()`` is unavailable — so it
        is captured through a subscriber attached before the stop. That recording
        is precisely what a persistence subscriber would have written, which is
        what makes this the end-to-end case rather than a restatement of the
        replay tests above.

        The captured messages are subscriber snapshots, with every live address
        already replaced by a proxy. That is fine: ``restore_message`` does no
        address resolution — resolving proxies back to live refs belongs to the
        team layer, in another package.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        persisted = _EventRecordingSubscriber()
        orch_proxy.subscribe(persisted)

        _occupy_worker(system, worker_addr)
        event: threading.Event = orch_proxy.stop(_GRACE_S)
        assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert len(_stopping_events(persisted)) == 1, "captured log holds no announcement"
        expected = _ids([msg for msg in persisted.messages if not _is_announcement(msg)])
        assert expected, "captured log holds nothing but the announcement"

        restored, recorder = _orchestrator_with_recorder(system)
        for message in persisted.messages:
            restored.restore_message(message)

        assert _stopping_events(recorder) == []
        assert restored.get_events(event_class=TeamStoppingEvent) == []
        assert _ids(recorder.messages) == expected
