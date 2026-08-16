"""Tests for ``on_stop_request`` — the begin-signal of an orchestrator teardown.

``on_stop`` fires at the END of teardown, after the mailbox has drained. The
drain still delivers ``ProcessedMessage``s, so a subscriber running a countdown
off the telemetry stream learns of the stop too late to keep that countdown from
being re-armed behind its back. ``on_stop_request`` is the symmetric partner:
dispatched at the START of ``Orchestrator.stop()``, before a single child is
told to stop.

The ordering is pinned by orchestrator state observed AT dispatch time, not by
wall-clock luck: ``_stop_non_tool_children()`` uses fire-and-forget tells, so a
child recording its own stop into a shared list would race the orchestrator's
thread and the test would be flaky-GREEN — it would keep passing with the
dispatch in the wrong place. ``_stopping``, ``_stop_backstop`` and
``_pending_tool_stops`` are all set synchronously on the actor thread.

Deliberately a NEW module: ``test_orchestrator_stop.py`` holds the non-blocking
stop harness and must stay untouched.
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
from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.messages.message import Message, UserMessage
from akgentic.core.orchestrator import Orchestrator

# Signals the moment the worker is INSIDE its handler, so the stop below arrives
# while the team is genuinely busy and the roster cannot empty instantly.
_in_handler = threading.Event()

# How long the worker holds its handler open once the stop has been requested.
_HANDLER_HOLD_S = 0.5

# Backstop grace passed to stop(); the watchdog bounds the TEST, not the stop.
_GRACE_S = 5.0
_WATCHDOG_S = 10.0

# One record per lifecycle dispatch: (event_method, _stopping, backstop armed,
# len(_pending_tool_stops), roster empty). Module-level because the interesting
# records are written while the orchestrator is tearing itself down — by the time
# a test can ask, the actor is gone. Same shape as ``_tool_stop_order`` in
# ``test_orchestrator_stop.py``.
LifecycleRecord = tuple[str, bool, bool, int, bool]
_lifecycle_records: list[LifecycleRecord] = []


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Reset the shared observation state and stop leaked actors after each test."""
    _lifecycle_records.clear()
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


class _ProbeOrchestrator(Orchestrator):
    """Records the orchestrator state visible at every lifecycle dispatch.

    The override runs on the actor thread, inside the very call it observes, so
    each record is a synchronous snapshot of how far ``stop()`` has progressed.
    """

    @override
    def _notify_subscribers_lifecycle(
        self,
        event_method: str,
        team_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        _lifecycle_records.append(
            (
                event_method,
                self._stopping,
                self._stop_backstop is not None,
                len(self._pending_tool_stops),
                self.get_team() == [],
            )
        )
        super()._notify_subscribers_lifecycle(event_method, team_id, **kwargs)

    def lifecycle_records(self) -> list[LifecycleRecord]:
        """Public façade over the recorded dispatches (Pykka filters ``_`` members)."""
        return list(_lifecycle_records)


class _LifecycleDrivingOrchestrator(Orchestrator):
    """Exposes lifecycle dispatch so a test can drive ``set_restoring`` directly.

    ``set_restoring`` has no core-side trigger — ``TeamManager`` drives it around
    a restore replay — so a public façade is the only way to exercise it here.
    Mirrors ``_NotifyExposingOrchestrator`` in ``test_orchestrator.py``.
    """

    def notify_subscribers_lifecycle(
        self,
        event_method: str,
        team_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Public façade over ``_notify_subscribers_lifecycle`` for proxy-driven tests."""
        self._notify_subscribers_lifecycle(event_method, team_id, **kwargs)


class _HookRecordingSubscriber:
    """Records the ORDER of the lifecycle hooks it is dispatched."""

    def __init__(self) -> None:
        self.hooks: list[str] = []
        self.messages: list[Message] = []

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        self.hooks.append("set_restoring")

    def on_stop_request(self, team_id: uuid.UUID) -> None:
        self.hooks.append("on_stop_request")

    def on_stop(self, team_id: uuid.UUID) -> None:
        self.hooks.append("on_stop")

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)


class _NoStopRequestSubscriber:
    """A subscriber predating the hook: everything BUT ``on_stop_request``."""

    def __init__(self) -> None:
        self.hooks: list[str] = []
        self.messages: list[Message] = []

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        self.hooks.append("set_restoring")

    def on_stop(self, team_id: uuid.UUID) -> None:
        self.hooks.append("on_stop")

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)


class _MessageOnlySubscriber:
    """The narrowest useful subscriber — no lifecycle hook at all."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)


class _RaisingStopRequestSubscriber:
    """Blows up inside ``on_stop_request``; the chain must survive it."""

    def on_stop_request(self, team_id: uuid.UUID) -> None:
        raise RuntimeError("subscriber exploded in on_stop_request")


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


def _error_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The ERROR-and-above records only — what "logs no error" actually means.

    ``caplog.records`` accumulates across the whole test, including the team
    setup that runs OUTSIDE the ``at_level`` block, so asserting the capture is
    entirely empty would turn red on any unrelated WARNING logged during setup —
    a failure about something these tests never claimed.
    """
    return [record.message for record in caplog.records if record.levelno >= logging.ERROR]


class TestStopRequestDispatchOrdering:
    """``on_stop_request`` is dispatched before any teardown work happens."""

    def test_stop_request_precedes_every_teardown_phase(self) -> None:
        """The hook fires with the stop path untouched, and ``on_stop`` at the end.

        Each record is taken synchronously inside the dispatch, so the assertions
        describe where ``stop()`` had got to — not which thread won a race.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system, _ProbeOrchestrator)
        orch_proxy = system.proxy_ask(orch_addr, _ProbeOrchestrator)

        assert orch_proxy.lifecycle_records() == [], "team setup dispatched a lifecycle hook"

        _occupy_worker(system, worker_addr)
        event: threading.Event = orch_proxy.stop(_GRACE_S)
        assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        methods = [record[0] for record in _lifecycle_records]
        assert methods == ["on_stop_request", "on_stop"]

        stop_request, on_stop = _lifecycle_records
        _, stopping, backstop_armed, pending_tools, roster_empty = stop_request
        assert stopping is False, "dispatched after self._stopping was set"
        assert backstop_armed is False, "dispatched after the backstop was armed"
        assert pending_tools == 0, "dispatched after phase 1 stopped the non-tool children"
        assert roster_empty is False, "the team was already gone at dispatch time"

        assert on_stop[1] is True, "on_stop dispatched before self._stopping was set"
        assert on_stop[4] is True, "on_stop dispatched before the roster drained"

    def test_a_second_stop_does_not_reraise_the_hook(self) -> None:
        """Two ``stop()`` calls share one event and dispatch the hook exactly once.

        The idempotency early-return sits ABOVE the dispatch on purpose: a
        subscriber that has already released everything must not be told a
        second time that teardown is beginning.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        recorder = _HookRecordingSubscriber()
        orch_proxy.subscribe(recorder)

        _occupy_worker(system, worker_addr)
        first: threading.Event = orch_proxy.stop(_GRACE_S)
        second: threading.Event = orch_proxy.stop(_GRACE_S)

        assert first is second
        assert first.wait(timeout=_WATCHDOG_S), "stop never completed"
        assert recorder.hooks.count("on_stop_request") == 1

    def test_a_subscriber_sees_both_hooks_in_order(self) -> None:
        """One graceful stop yields exactly ``["on_stop_request", "on_stop"]``."""
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        recorder = _HookRecordingSubscriber()
        orch_proxy.subscribe(recorder)

        _occupy_worker(system, worker_addr)
        event: threading.Event = orch_proxy.stop(_GRACE_S)
        assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert recorder.hooks == ["on_stop_request", "on_stop"]


class TestSubscribersWithoutTheHook:
    """A subscriber that never heard of ``on_stop_request`` keeps working."""

    def test_subscriber_without_the_hook_still_gets_the_others(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It registers, receives ``set_restoring``/``on_message``/``on_stop``, logs no ERROR.

        The Protocol's ``...`` body is a static-typing default only: at runtime a
        structurally-typed subscriber simply has no such attribute, and the
        dispatch must skip it rather than log an error on every stop.
        """
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system, _LifecycleDrivingOrchestrator)
        orch_proxy = system.proxy_ask(orch_addr, _LifecycleDrivingOrchestrator)
        subscriber = _NoStopRequestSubscriber()
        orch_proxy.subscribe(subscriber)
        team_id: uuid.UUID = orch_proxy.team_id

        _occupy_worker(system, worker_addr)
        with caplog.at_level(logging.ERROR):
            orch_proxy.notify_subscribers_lifecycle("set_restoring", team_id, restoring=True)
            event: threading.Event = orch_proxy.stop(_GRACE_S)
            assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert subscriber.hooks == ["set_restoring", "on_stop"]
        assert _error_messages(caplog) == []
        assert subscriber.messages, "subscriber never received any telemetry"

    def test_message_only_subscriber_logs_no_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """A subscriber defining ONLY ``on_message`` survives a full stop silently."""
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        subscriber = _MessageOnlySubscriber()
        orch_proxy.subscribe(subscriber)

        _occupy_worker(system, worker_addr)
        with caplog.at_level(logging.ERROR):
            event: threading.Event = orch_proxy.stop(_GRACE_S)
            assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert _error_messages(caplog) == []
        assert subscriber.messages, "subscriber never received any telemetry"


class TestRaisingSubscriberDoesNotBreakTheChain:
    """A hook that EXISTS and raises is still caught and logged, as before."""

    def test_a_raising_subscriber_does_not_stop_the_dispatch(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The next subscriber still gets the hook, the stop still completes."""
        system = ActorSystem()
        orch_addr, worker_addr = _build_busy_team(system)
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)
        orch_proxy.subscribe(_RaisingStopRequestSubscriber())
        recorder = _HookRecordingSubscriber()
        orch_proxy.subscribe(recorder)

        _occupy_worker(system, worker_addr)
        with caplog.at_level(logging.ERROR):
            event: threading.Event = orch_proxy.stop(_GRACE_S)
            assert event.wait(timeout=_WATCHDOG_S), "stop never completed"

        assert recorder.hooks == ["on_stop_request", "on_stop"]
        assert not orch_addr.is_alive()
        assert any("on_stop_request" in record.message for record in caplog.records)
