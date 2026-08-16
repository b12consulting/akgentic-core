"""Behaviour tests for the orchestrator's team-scoped metadata carrier.

``Orchestrator.team_metadata`` is a runtime attribute reached through
``get_metadata`` / ``set_metadata``. Two of these tests are deliberately
*negative* and load-bearing: they pin that setting metadata emits no
``StateChangedMessage`` (so nothing snapshots the value into the persisted
agent-state collection) and that ``team_metadata`` never becomes a field on
``BaseState``. A future "tidy-up" that moves the value into agent state fails
here instead of silently desynchronising the team record downstream consumers
index.

Everything is driven through the public proxy API (``ActorSystem.proxy_ask`` /
``proxy_tell``) — no test reaches through actor internals. Assertions are
behavioural only; nothing checks source text, docstrings or comments.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import pykka
import pytest

from akgentic.core.actor_address import ActorAddress
from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message
from akgentic.core.messages.orchestrator import StateChangedMessage
from akgentic.core.orchestrator import Orchestrator
from akgentic.core.utils.serializer import SerializableBaseModel


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Stop any leaked actors after each test so failures don't cascade."""
    yield
    pykka.ActorRegistry.stop_all()


class _Meta(SerializableBaseModel):
    """A caller-defined metadata contract. Placeholder values only."""

    tenant: str
    case: str | None = None


class _OtherMeta(SerializableBaseModel):
    """A differently-shaped contract, for the replace-not-merge test."""

    channel: str


class _WorkerState(BaseState):
    """Agent state with a field, so a state change is observable."""

    counter: int = 0


class _Worker(Akgent[BaseConfig, _WorkerState]):
    """Ordinary child agent — hired, fired, and made to change its state."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Base ``Akgent`` attaches no observer, and an unobserved state publishes
        # nothing — so without this attach nothing ever reaches the orchestrator's
        # state_dict and the ``!= {}`` guards below would be vacuously true.
        self.state = _WorkerState().observer(self)


class RecordingSubscriber:
    """Captures the orchestrator's subscriber fan-out for the negative test."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def on_message(self, msg: Message) -> None:
        self.messages.append(msg)

    # Lifecycle hooks — no-ops, present to satisfy the EventSubscriber protocol.
    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        ...

    def on_stop_request(self, team_id: uuid.UUID) -> None: ...

    def on_stop(self, team_id: uuid.UUID) -> None: ...


def _start_orchestrator(system: ActorSystem) -> ActorAddress:
    """Start a bare orchestrator and return its address."""
    return system.createActor(
        Orchestrator,
        config=BaseConfig(name="@Orchestrator", role="Orchestrator"),
    )


def test_get_metadata_returns_none_on_fresh_orchestrator() -> None:
    """AC1: a team that declares no metadata contract carries nothing."""
    system = ActorSystem()
    orch = _start_orchestrator(system)

    assert system.proxy_ask(orch, Orchestrator).get_metadata() is None

    system.shutdown()


def test_set_then_get_round_trips_concrete_subclass() -> None:
    """AC2/AC3: the getter returns the concrete subclass, not a base-coerced copy."""
    system = ActorSystem()
    orch = _start_orchestrator(system)
    proxy = system.proxy_ask(orch, Orchestrator)

    original = _Meta(tenant="acme", case="C-1234")
    proxy.set_metadata(original)

    result = proxy.get_metadata()
    assert type(result) is _Meta
    # Subclass-specific fields survive the round trip.
    assert result.tenant == "acme"
    assert result.case == "C-1234"

    system.shutdown()


def test_set_metadata_over_proxy_tell_is_visible_to_get_metadata() -> None:
    """AC3: the fire-and-forget production path lands.

    No sleep: the follow-up ``proxy_ask`` is queued behind the tell in the same
    actor mailbox, so the write is guaranteed applied before the read runs.
    """
    system = ActorSystem()
    orch = _start_orchestrator(system)

    system.proxy_tell(orch, Orchestrator).set_metadata(_Meta(tenant="contoso"))

    result = system.proxy_ask(orch, Orchestrator).get_metadata()
    assert isinstance(result, _Meta)
    assert result.tenant == "contoso"

    system.shutdown()


def test_second_set_replaces_and_does_not_merge() -> None:
    """AC4: replace semantics — "which fields are set" never depends on history."""
    system = ActorSystem()
    orch = _start_orchestrator(system)
    proxy = system.proxy_ask(orch, Orchestrator)

    proxy.set_metadata(_Meta(tenant="acme", case="C-1234"))
    proxy.set_metadata(_OtherMeta(channel="email"))

    result = proxy.get_metadata()
    assert type(result) is _OtherMeta
    assert result.channel == "email"
    # The first value's fields are gone, not merged in.
    assert not hasattr(result, "tenant")
    assert not hasattr(result, "case")

    system.shutdown()


def test_set_metadata_none_clears() -> None:
    """AC5: ``set_metadata(None)`` stores the clear, it is not ignored."""
    system = ActorSystem()
    orch = _start_orchestrator(system)
    proxy = system.proxy_ask(orch, Orchestrator)

    proxy.set_metadata(_Meta(tenant="acme"))
    assert proxy.get_metadata() is not None

    proxy.set_metadata(None)
    assert proxy.get_metadata() is None

    system.shutdown()


def test_set_metadata_emits_no_state_changed_message() -> None:
    """AC6 (load-bearing): metadata never enters the agent-state snapshot path.

    A ``StateChangedMessage`` here would be persisted into the agent-state
    collection by a downstream persistence subscriber, creating a second copy of
    the metadata that can diverge from the authoritative team record. This test
    is what stops a later refactor from moving the value into ``BaseState``.

    ``state_dict`` is populated *before* the recorder is attached, for two
    reasons: it makes the "no entry added **or modified**" half of the
    requirement real (comparing two empty dicts would only ever catch an
    addition), and it keeps the worker's own start/state telemetry out of the
    recorder. Both writes are already queued on the orchestrator's mailbox when
    ``subscribe`` is enqueued behind them, so the ordering is deterministic
    rather than timing-dependent.
    """
    system = ActorSystem()
    orch = _start_orchestrator(system)
    proxy = system.proxy_ask(orch, Orchestrator)

    worker = proxy.createActor(_Worker, config=BaseConfig(name="@Worker", role="Worker"))
    system.proxy_ask(worker, _Worker).init_state(_WorkerState(counter=7))

    recorder = RecordingSubscriber()
    proxy.subscribe(recorder)
    states_before = {aid: state.model_dump() for aid, state in proxy.get_states().items()}
    assert states_before != {}, "state_dict must be non-empty or the invariance check is weak"

    proxy.set_metadata(_Meta(tenant="acme", case="C-1234"))
    proxy.set_metadata(None)
    proxy.set_metadata(_OtherMeta(channel="email"))

    assert [m for m in recorder.messages if isinstance(m, StateChangedMessage)] == []
    assert recorder.messages == []
    states_after = {aid: state.model_dump() for aid, state in proxy.get_states().items()}
    assert states_after == states_before

    system.shutdown()


def test_team_metadata_is_not_a_base_state_field() -> None:
    """AC7 (load-bearing): the value is not, and must not become, agent state."""
    assert "team_metadata" not in BaseState.model_fields


def test_metadata_survives_hire_fire_and_unrelated_state_change() -> None:
    """AC8: metadata is team-scoped — agent lifecycle and state churn do not touch it."""
    system = ActorSystem()
    orch = _start_orchestrator(system)
    proxy = system.proxy_ask(orch, Orchestrator)

    original = _Meta(tenant="acme", case="C-1234")
    proxy.set_metadata(original)

    # Hire.
    worker = proxy.createActor(_Worker, config=BaseConfig(name="@Worker", role="Worker"))
    assert worker is not None
    assert proxy.get_metadata() == original

    # An unrelated agent mutates its own state, which the orchestrator snapshots.
    system.proxy_ask(worker, _Worker).init_state(_WorkerState(counter=7))
    assert proxy.get_states() != {}
    assert proxy.get_metadata() == original

    # Fire.
    system.proxy_ask(worker, Akgent).stop()
    result = proxy.get_metadata()
    assert type(result) is _Meta
    assert result.tenant == "acme"
    assert result.case == "C-1234"

    system.shutdown()
