"""Tests for ResourceHost: get-or-create by name, the store contract, and reclamation.

Every behavioural assertion goes through the public seam — the address the host hands
back, a pykka proxy, or a message. Two structural facts (the host's ``_children`` and a
hosted actor's ``_parent``) are unreachable through a proxy, which refuses any name
starting with an underscore, so those two read the live actor object through
``_actor_of``. That helper is legal here and only here: core owns the actor
implementation.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Generator
from typing import Any, ClassVar, cast

import pykka
import pytest
from pydantic import JsonValue

from akgentic.core.actor_address import ActorAddress
from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import ResourceStopped, UserMessage
from akgentic.core.messages.orchestrator import StartMessage
from akgentic.core.orchestrator import Orchestrator
from akgentic.core.resource_host import (
    ResourceHost,
    ResourceStore,
    StateDelta,
    resolve_state_type,
)
from akgentic.core.utils.deserializer import deserialize_object

HOST_LOGGER = "akgentic.core.resource_host"
TIMEOUT = 10.0


##
## Helpers
##
def _proxy(address: ActorAddress) -> pykka.ActorProxy[Any]:
    """A pykka proxy onto the actor behind *address* — the public seam."""
    return cast(ActorAddressImpl, address)._actor_ref.proxy()


def _actor_of(address: ActorAddress) -> Akgent[Any, Any]:
    """The live actor behind an address; legal here because core owns the actor impl."""
    actor = cast(ActorAddressImpl, address)._actor_ref._actor_weakref()
    assert actor is not None, "actor was garbage collected"
    return cast("Akgent[Any, Any]", actor)


def _get_or_create(host: ActorAddress, name: str) -> ActorAddress:
    """Ask the host for the resource named *name*, creating a ``_CountingActor`` on a miss."""
    future = _proxy(host).getResourceOrCreate(_CountingActor, BaseConfig(name=name))
    return cast(ActorAddress, future.get(timeout=TIMEOUT))


def _get_or_create_kind(
    host: ActorAddress, actor_class: type[Akgent[Any, Any]], name: str
) -> ActorAddress:
    """Ask the host for *name*, creating *actor_class* on a miss."""
    future = _proxy(host).getResourceOrCreate(actor_class, BaseConfig(name=name))
    return cast(ActorAddress, future.get(timeout=TIMEOUT))


def _drop_entry(host: ActorAddress, name: str) -> None:
    """Announce that the resource at *name* stopped, and wait for the host to act."""
    host.tell(ResourceStopped(scope=name))
    _flush(host)


def _register_store(host: ActorAddress, store: ResourceStore) -> None:
    """Attach *store* to the host and wait for the assignment to land."""
    _proxy(host).register_store(store).get(timeout=TIMEOUT)


def _flush(address: ActorAddress) -> None:
    """Block until everything already queued for *address* has been handled.

    One FIFO mailbox serves messages, proxy calls and attribute reads alike, so an
    attribute read that has resolved proves every earlier envelope was processed.
    """
    _proxy(address).config.get(timeout=TIMEOUT)


def _state_of(address: ActorAddress) -> Any:
    """The hosted actor's current state, read through the proxy."""
    return _proxy(address).state.get(timeout=TIMEOUT)


def _wait_until_stopped(address: ActorAddress, timeout: float = 5.0) -> bool:
    """Poll until *address* reports stopped, or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not address.is_alive():
            return True
        time.sleep(0.01)
    return False


def _host_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Records emitted by the host's own logger at WARNING or above."""
    return [
        record
        for record in caplog.records
        if record.name == HOST_LOGGER and record.levelno >= logging.WARNING
    ]


##
## Test doubles
##
class _HostedState(BaseState):
    """State of the hosted actor used throughout this module."""

    value: str = "default"
    counter: int = 0


class _StateWithExtraField(_HostedState):
    """A state carrying a field the host has never heard of (Golden Rule 12)."""

    extra_field: str = "sentinel"


class _CountingActor(Akgent[BaseConfig, _HostedState]):
    """Hosted actor recording each construction, restoration, message and stop."""

    constructions: ClassVar[list[uuid.UUID]] = []
    lifecycle: ClassVar[list[str]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = _HostedState()
        _CountingActor.constructions.append(self.agent_id)

    def init_state(self, state: _HostedState) -> None:
        _CountingActor.lifecycle.append("init")
        super().init_state(state)

    def receiveMsg_UserMessage(self, message: UserMessage) -> None:
        _CountingActor.lifecycle.append("ping")

    def on_stop(self) -> None:
        _CountingActor.lifecycle.append("stopped")
        super().on_stop()


class _AlphaState(BaseState):
    """One resource kind's state. Its fields do not overlap ``_BetaState``'s."""

    alpha: str = "alpha-default"


class _BetaState(BaseState):
    """The other kind's state, so a document written for one cannot validate as the other."""

    beta: int = -1


class _AlphaActor(Akgent[BaseConfig, _AlphaState]):
    """A hosted actor of the first kind."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = _AlphaState()


class _BetaActor(Akgent[BaseConfig, _BetaState]):
    """A hosted actor of the second kind, with a different state type."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = _BetaState()


class _DerivedAlphaActor(_AlphaActor):
    """A subclass adding no type parameters — its state type is found up the MRO."""


class _UnparameterisedActor(Akgent):  # type: ignore[type-arg]
    """An ``Akgent`` subclass with no type arguments: both arguments are TypeVars."""


class _NoStateActor(Akgent[BaseConfig, None]):  # type: ignore[type-var]
    """``Akgent[BaseConfig, None]`` — a real shape in this repo, and not a ``BaseState``."""


class _RichConfig(BaseConfig):
    """A config type that is not ``BaseConfig``, so position 0 and 1 differ visibly."""

    extra: str = "rich"


class _RichAlphaActor(Akgent[_RichConfig, _AlphaState]):
    """Both type arguments concrete and distinct — the resolver must answer the state."""


class _TypedStore:
    """A store keyed on ``(actor_class, scope)`` that holds raw documents, not states.

    Documents are plain dicts assembled from ``StateDelta`` keys, exactly as a real store
    would hold them: nothing here carries a root type marker, so ``load`` can only rebuild
    by asking :func:`resolve_state_type` what class the actor declared. A store that
    ignored ``actor_class`` could not answer at all, which is what stops the two-kind spec
    passing vacuously.
    """

    def __init__(self) -> None:
        self.documents: dict[tuple[type[Akgent[Any, Any]], str], dict[str, JsonValue]] = {}

    def load(self, actor_class: type[Akgent[Any, Any]], scope: str) -> BaseState | None:
        document = self.documents.get((actor_class, scope))
        if document is None:
            return None
        state_type = resolve_state_type(actor_class)
        if state_type is None:
            return None
        return state_type.model_validate(document)

    def apply(self, actor_class: type[Akgent[Any, Any]], scope: str, delta: StateDelta) -> None:
        document = self.documents.setdefault((actor_class, scope), {})
        document.update(delta.set)
        for key in delta.unset:
            document.pop(key, None)


class _FakeStore:
    """Records every call and returns whatever state it was seeded with.

    Calls are recorded as ``(actor_class, scope)`` rather than a bare scope, so a spec
    can assert *which class* reached the store and not merely that one did.
    """

    def __init__(self, state: BaseState | None = None) -> None:
        self.state = state
        self.load_calls: list[tuple[type[Akgent[Any, Any]], str]] = []
        self.apply_calls: list[tuple[type[Akgent[Any, Any]], str, StateDelta]] = []

    def load(self, actor_class: type[Akgent[Any, Any]], scope: str) -> BaseState | None:
        self.load_calls.append((actor_class, scope))
        return self.state

    def apply(self, actor_class: type[Akgent[Any, Any]], scope: str, delta: StateDelta) -> None:
        self.apply_calls.append((actor_class, scope, delta))


class _FailingStore:
    """Raises from ``apply`` always, and from ``load`` unless told otherwise.

    The two failures are separable on purpose. A store that raises from both puts a
    ``load`` record in ``caplog`` before the ``apply`` path is ever exercised, so an
    assertion that only looks for the scope string is satisfied by the wrong record.
    """

    def __init__(self, *, fail_load: bool = True) -> None:
        self.fail_load = fail_load
        self.load_calls: list[tuple[type[Akgent[Any, Any]], str]] = []
        self.apply_calls: list[tuple[type[Akgent[Any, Any]], str]] = []

    def load(self, actor_class: type[Akgent[Any, Any]], scope: str) -> BaseState | None:
        self.load_calls.append((actor_class, scope))
        if self.fail_load:
            raise RuntimeError("store unreachable")
        return None

    def apply(self, actor_class: type[Akgent[Any, Any]], scope: str, delta: StateDelta) -> None:
        self.apply_calls.append((actor_class, scope))
        raise RuntimeError("store unreachable")


##
## Fixtures
##
@pytest.fixture(autouse=True)
def reset_class_state() -> Generator[None, None, None]:
    """Clear the hosted actor's class-level ledgers and stop every leaked actor."""
    _CountingActor.constructions.clear()
    _CountingActor.lifecycle.clear()
    yield
    _CountingActor.constructions.clear()
    _CountingActor.lifecycle.clear()
    pykka.ActorRegistry.stop_all()


@pytest.fixture
def system() -> Generator[ActorSystem, None, None]:
    """A live actor system, torn down after each test."""
    actor_system = ActorSystem()
    yield actor_system
    actor_system.shutdown()


@pytest.fixture
def host(system: ActorSystem) -> ActorAddress:
    """A ResourceHost with no store registered — cold, as a fresh process is."""
    return system.createActor(
        ResourceHost, config=BaseConfig(name="#ResourceHost", role="ResourceHost")
    )


##
## AC #1 — the delta
##
class TestStateDelta:
    """StateDelta is a plain serializable model with two fields."""

    def test_defaults_are_empty(self) -> None:
        delta = StateDelta()
        assert delta.set == {}
        assert delta.unset == []

    def test_round_trips_through_serialization(self) -> None:
        delta = StateDelta(set={"documents.notes/a.pdf": {"pages": 3}}, unset=["rag_index.old"])
        restored = deserialize_object(delta.model_dump())
        assert isinstance(restored, StateDelta)
        assert restored == delta

    def test_values_are_stored_verbatim(self) -> None:
        value: JsonValue = {"nested": [1, 2.5, "three", True, None], "flag": False}
        delta = StateDelta(set={"k": value})
        assert delta.set["k"] == value
        assert deserialize_object(delta.model_dump()).set["k"] == value


##
## AC #2 — the store contract
##
class TestResourceStoreProtocol:
    """ResourceStore is a runtime-checkable Protocol with exactly two methods."""

    def test_declares_exactly_load_and_apply(self) -> None:
        declared = {
            name
            for name, value in vars(ResourceStore).items()
            if callable(value) and not name.startswith("_")
        }
        assert declared == {"load", "apply"}

    def test_conforming_fake_passes_isinstance(self) -> None:
        assert isinstance(_FakeStore(), ResourceStore)
        assert isinstance(_FailingStore(), ResourceStore)

    def test_missing_method_fails_isinstance(self) -> None:
        class _LoadOnly:
            def load(self, scope: str) -> BaseState | None:
                return None

        assert not isinstance(_LoadOnly(), ResourceStore)


##
## AC #3 — cold and hot take the same path
##
class TestColdAndHotFlowsAreIdentical:
    """A store changes which calls are made, never what the caller observes."""

    @staticmethod
    def _sequence(host: ActorAddress, name: str) -> tuple[bool, str, int]:
        """Get-or-create, read the state back, write a delta back. Cold or hot."""
        address = _get_or_create(host, name)
        state = _state_of(address)
        _proxy(host).notify_delta(name, StateDelta(set={"value": "written"})).get(timeout=TIMEOUT)
        return address.is_alive(), state.value, state.counter

    def test_the_observable_flow_does_not_change_when_a_store_arrives(
        self, host: ActorAddress
    ) -> None:
        cold = self._sequence(host, "#Resource-cold")

        store = _FakeStore()
        _register_store(host, store)
        hot = self._sequence(host, "#Resource-hot")

        assert cold == (True, "default", 0)
        assert hot == cold
        assert store.load_calls == [(_CountingActor, "#Resource-hot")]
        assert [(cls, scope) for cls, scope, _ in store.apply_calls] == [
            (_CountingActor, "#Resource-hot")
        ]


##
## AC #4, #5 — get-or-create
##
class TestGetOrCreate:
    """Keyed on config.name, serialised by the host's mailbox, dead entries replaced."""

    def test_same_name_yields_one_actor(self, host: ActorAddress) -> None:
        first = _get_or_create(host, "#Resource-a")
        second = _get_or_create(host, "#Resource-a")

        assert first.agent_id == second.agent_id
        assert len(_CountingActor.constructions) == 1

    def test_different_names_yield_two_actors(self, host: ActorAddress) -> None:
        first = _get_or_create(host, "#Resource-a")
        second = _get_or_create(host, "#Resource-b")

        assert first.agent_id != second.agent_id
        assert len(_CountingActor.constructions) == 2

    def test_dead_entry_is_a_miss_and_is_replaced_not_duplicated(self, host: ActorAddress) -> None:
        first = _get_or_create(host, "#Resource-dead")
        cast(ActorAddressImpl, first)._actor_ref.stop(block=True)
        assert not first.is_alive()

        second = _get_or_create(host, "#Resource-dead")
        assert second.is_alive()
        assert second.agent_id != first.agent_id
        assert len(_CountingActor.constructions) == 2

        third = _get_or_create(host, "#Resource-dead")
        assert third.agent_id == second.agent_id
        assert len(_CountingActor.constructions) == 2


##
## AC #6 — a hosted actor is owned by nobody
##
class TestHostedActorIsUnowned:
    """No orchestrator, no parent, nobody's child, its own team."""

    def test_hosted_actor_joins_no_tree_and_no_team(
        self, system: ActorSystem, host: ActorAddress
    ) -> None:
        orchestrator = system.createActor(
            Orchestrator, config=BaseConfig(name="#Orchestrator", role="Orchestrator")
        )
        address = _get_or_create(host, "#Resource-free")

        assert _proxy(address).orchestrator.get(timeout=TIMEOUT) is None
        assert _actor_of(host)._children == []
        assert _actor_of(address)._parent is None

        # A control actor the orchestrator *does* own. Without it both negatives below
        # are vacuous: an orchestrator that saw nothing at all would satisfy them just
        # as well as one that correctly excludes the hosted actor.
        control = cast(
            ActorAddress,
            _proxy(orchestrator)
            .createActor(_CountingActor, None, BaseConfig(name="#Control"))
            .get(timeout=TIMEOUT),
        )

        roster_ids = {
            member.agent_id for member in _proxy(orchestrator).get_team().get(timeout=TIMEOUT)
        }
        assert control.agent_id in roster_ids
        assert address.agent_id not in roster_ids

        starts = _proxy(orchestrator).get_messages(None, StartMessage).get(timeout=TIMEOUT)
        start_senders = {
            message.sender.agent_id for message in starts if message.sender is not None
        }
        assert control.agent_id in start_senders
        assert address.agent_id not in start_senders

        assert isinstance(address.team_id, uuid.UUID)
        assert address.team_id != orchestrator.team_id


##
## AC #7, #11 — restore
##
class TestRestore:
    """Loaded state reaches the actor through init_state, ahead of the caller's mail."""

    def test_restored_state_lands_before_a_later_message(self, host: ActorAddress) -> None:
        _register_store(host, _FakeStore(_HostedState(value="restored", counter=7)))

        address = _get_or_create(host, "#Resource-restored")
        address.tell(UserMessage(content="ping"))

        state = _state_of(address)
        assert state.value == "restored"
        assert state.counter == 7
        assert _CountingActor.lifecycle == ["init", "ping"]

    def test_unknown_state_field_survives_the_round_trip(self, host: ActorAddress) -> None:
        _register_store(host, _FakeStore(_StateWithExtraField(value="restored", counter=3)))

        address = _get_or_create(host, "#Resource-extra")
        restored = _state_of(address)

        assert isinstance(restored, _StateWithExtraField)
        assert restored.extra_field == "sentinel"
        assert restored.value == "restored"
        assert restored.counter == 3


##
## AC #8 — a failing store
##
class TestFailingStore:
    """The caller keeps its address, the host keeps answering, the failure is logged."""

    def test_failing_load_still_returns_a_live_address(
        self, host: ActorAddress, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = _FailingStore()
        _register_store(host, store)

        with caplog.at_level(logging.WARNING, logger=HOST_LOGGER):
            address = _get_or_create(host, "#Resource-broken")

        assert address.is_alive()
        state = _state_of(address)
        assert state.value == "default"
        assert store.load_calls == [(_CountingActor, "#Resource-broken")]
        records = _host_records(caplog)
        assert any(
            "store load failed" in record.getMessage() and "#Resource-broken" in record.getMessage()
            for record in records
        )
        # The other path's record must be absent — caplog accumulates, so a bare
        # "some record mentions the scope" assertion is satisfiable by the wrong one.
        assert not any("store apply failed" in record.getMessage() for record in records)
        # Non-load-bearing: pykka keeps an actor whose handler raised, so this passes
        # with the guard deleted. Kept for completeness only — see the completion notes.
        assert host.is_alive()

    def test_failing_apply_does_not_reach_the_caller(
        self, host: ActorAddress, caplog: pytest.LogCaptureFixture
    ) -> None:
        # load succeeds here so the only failure record in caplog is the apply one.
        store = _FailingStore(fail_load=False)
        _register_store(host, store)
        address = _get_or_create(host, "#Resource-broken")

        with caplog.at_level(logging.WARNING, logger=HOST_LOGGER):
            _proxy(host).notify_delta("#Resource-broken", StateDelta(unset=["gone"])).get(
                timeout=TIMEOUT
            )

        assert store.apply_calls == [(_CountingActor, "#Resource-broken")]
        records = _host_records(caplog)
        assert any(
            "store apply failed" in record.getMessage()
            and "#Resource-broken" in record.getMessage()
            for record in records
        )
        assert not any("store load failed" in record.getMessage() for record in records)

        again = _get_or_create(host, "#Resource-broken")
        assert again.agent_id == address.agent_id
        assert host.is_alive()


##
## AC #9 — shutdown, and what the host must not do
##
class TestShutdown:
    """The system stops a hosted actor gracefully; the host never does."""

    def test_system_shutdown_runs_the_hosted_actor_on_stop(
        self, system: ActorSystem, host: ActorAddress
    ) -> None:
        address = _get_or_create(host, "#Resource-shutdown")
        assert address.is_alive()
        assert "stopped" not in _CountingActor.lifecycle

        system.shutdown()

        assert not address.is_alive()
        assert not host.is_alive()
        assert "stopped" in _CountingActor.lifecycle

    def test_stopping_the_host_leaves_the_hosted_actor_running(self, host: ActorAddress) -> None:
        address = _get_or_create(host, "#Resource-orphan")

        _proxy(host).stop().get(timeout=TIMEOUT)

        assert _wait_until_stopped(host)
        assert address.is_alive()
        assert "stopped" not in _CountingActor.lifecycle


##
## AC #10 — reclamation
##
class TestResourceStopped:
    """The entry goes; the actor and the stored document stay."""

    def test_drops_the_entry_and_nothing_else(self, host: ActorAddress) -> None:
        store = _FakeStore()
        _register_store(host, store)
        address = _get_or_create(host, "#Resource-gone")
        store.load_calls.clear()

        host.tell(ResourceStopped(scope="#Resource-gone"))
        _flush(host)

        assert store.load_calls == []
        assert store.apply_calls == []
        assert address.is_alive()
        assert "stopped" not in _CountingActor.lifecycle

        replacement = _get_or_create(host, "#Resource-gone")
        assert replacement.agent_id != address.agent_id
        assert len(_CountingActor.constructions) == 2
        assert store.load_calls == [(_CountingActor, "#Resource-gone")]

    def test_unknown_scope_is_harmless(self, host: ActorAddress) -> None:
        address = _get_or_create(host, "#Resource-known")

        host.tell(ResourceStopped(scope="#Resource-never-hosted"))
        _flush(host)

        assert host.is_alive()
        assert _get_or_create(host, "#Resource-known").agent_id == address.agent_id


##
## 33-3 AC #1 — the Protocol takes the class first
##
class TestStoreProtocolTakesTheClassFirst:
    """The re-signatured Protocol still has exactly two methods and still accepts a fake.

    ``runtime_checkable`` proves method *presence* only — it has never checked
    signatures, so a stale two-argument store passes ``isinstance`` too and only ``mypy``
    catches the drift. That is precisely why this is not the story's guard; the guard is
    :class:`TestTwoKindsAtOneScope`.
    """

    def test_still_declares_exactly_load_and_apply(self) -> None:
        declared = {
            name
            for name, value in vars(ResourceStore).items()
            if callable(value) and not name.startswith("_")
        }
        assert declared == {"load", "apply"}

    def test_a_class_first_fake_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeStore(), ResourceStore)
        assert isinstance(_TypedStore(), ResourceStore)

    def test_runtime_checkable_does_not_catch_a_stale_two_argument_store(self) -> None:
        class _StaleStore:
            """The pre-33-3 shape. Recorded, not condoned: mypy is the only gate."""

            def load(self, scope: str) -> BaseState | None:
                return None

            def apply(self, scope: str, delta: StateDelta) -> None:
                return None

        assert isinstance(_StaleStore(), ResourceStore)


##
## 33-3 AC #2 — the class reaches the store on both paths
##
class TestTheClassReachesTheStore:
    """``load`` gets the caller's class; ``apply`` gets the registry entry's."""

    def test_load_and_apply_both_receive_the_class_the_caller_asked_for(
        self, host: ActorAddress
    ) -> None:
        store = _FakeStore()
        _register_store(host, store)

        _get_or_create_kind(host, _AlphaActor, "P")
        assert store.load_calls == [(_AlphaActor, "P")]

        delta = StateDelta(set={"alpha": "written"})
        _proxy(host).notify_delta("P", delta).get(timeout=TIMEOUT)

        assert store.apply_calls == [(_AlphaActor, "P", delta)]

    def test_apply_uses_the_registered_class_not_the_most_recent_one(
        self, host: ActorAddress
    ) -> None:
        # Two scopes, two kinds. If ``notify_delta`` took the class from anywhere but the
        # entry for *its own* scope, one of these two would carry the other's class.
        store = _FakeStore()
        _register_store(host, store)

        _get_or_create_kind(host, _AlphaActor, "P-alpha")
        _get_or_create_kind(host, _BetaActor, "P-beta")

        _proxy(host).notify_delta("P-alpha", StateDelta(set={"alpha": "a"})).get(timeout=TIMEOUT)
        _proxy(host).notify_delta("P-beta", StateDelta(set={"beta": 1})).get(timeout=TIMEOUT)

        assert [(cls, scope) for cls, scope, _ in store.apply_calls] == [
            (_AlphaActor, "P-alpha"),
            (_BetaActor, "P-beta"),
        ]


##
## 33-3 AC #3 — THE GUARD: two kinds at one scope are two documents
##
class TestTwoKindsAtOneScope:
    """One host, one scope string, two actor classes, two documents.

    This is the story's central guard and the only spec that can tell this design from
    the one it replaces: a store keyed on the scope alone would hand Beta the document
    Alpha wrote, and could not rebuild either into a concrete state at all. Deliberately
    one host and sequential — two ``ResourceHost``s in one process is the defect the epic
    exists to remove and must not appear in a test.
    """

    def test_two_kinds_at_one_scope_do_not_share_a_document(self, host: ActorAddress) -> None:
        store = _TypedStore()
        _register_store(host, store)

        # 1. Alpha at scope "P", writing a value only _AlphaState has a field for.
        alpha = _get_or_create_kind(host, _AlphaActor, "P")
        _proxy(host).notify_delta("P", StateDelta(set={"alpha": "written-by-alpha"})).get(
            timeout=TIMEOUT
        )
        assert store.documents[(_AlphaActor, "P")] == {"alpha": "written-by-alpha"}
        alpha_document_before = dict(store.documents[(_AlphaActor, "P")])

        # 2. Alpha stops and its entry goes; the stored document deliberately survives.
        cast(ActorAddressImpl, alpha)._actor_ref.stop(block=True)
        _drop_entry(host, "P")

        # 3. Beta at the SAME scope "P". Its load must miss, because the document that
        #    exists is Alpha's and is not keyed under Beta.
        beta = _get_or_create_kind(host, _BetaActor, "P")
        beta_state = _state_of(beta)

        assert isinstance(beta_state, _BetaState)
        assert beta_state == _BetaState()
        assert beta_state.beta == -1

        # 4. Beta writes its own delta. Alpha's document must not move.
        _proxy(host).notify_delta("P", StateDelta(set={"beta": 7})).get(timeout=TIMEOUT)

        assert store.documents[(_BetaActor, "P")] == {"beta": 7}
        assert store.documents[(_AlphaActor, "P")] == alpha_document_before
        assert set(store.documents) == {(_AlphaActor, "P"), (_BetaActor, "P")}

        # 5. Alpha comes back at "P" and restores its own values, intact and typed.
        cast(ActorAddressImpl, beta)._actor_ref.stop(block=True)
        _drop_entry(host, "P")

        alpha_again = _get_or_create_kind(host, _AlphaActor, "P")
        restored = _state_of(alpha_again)

        assert isinstance(restored, _AlphaState)
        assert restored.alpha == "written-by-alpha"


##
## 33-3 AC #4 — a delta for an unregistered scope is dropped, not written
##
class TestUnregisteredScopeDeltaIsDropped:
    """The host cannot invent a class, so it drops the delta rather than guessing one."""

    def test_delta_after_resource_stopped_is_not_written_and_is_logged(
        self, host: ActorAddress, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A distinctive scope on purpose: asserting a one-character scope appears in the
        # record would be satisfied by almost any message the host could emit.
        scope = "#Resource-dropped-scope"
        store = _FakeStore()
        _register_store(host, store)
        _get_or_create_kind(host, _AlphaActor, scope)
        _drop_entry(host, scope)

        with caplog.at_level(logging.WARNING, logger=HOST_LOGGER):
            _proxy(host).notify_delta(scope, StateDelta(set={"alpha": "lost"})).get(timeout=TIMEOUT)

        # The absence of the store call is the guard; the log is corroboration.
        assert store.apply_calls == []
        assert host.is_alive()
        assert any(
            "delta dropped" in record.getMessage() and scope in record.getMessage()
            for record in _host_records(caplog)
        )

    def test_a_registered_scope_is_still_written(self, host: ActorAddress) -> None:
        # Without this the spec above is satisfiable by a host that never writes at all.
        store = _FakeStore()
        _register_store(host, store)
        _get_or_create_kind(host, _AlphaActor, "P")

        _proxy(host).notify_delta("P", StateDelta(set={"alpha": "kept"})).get(timeout=TIMEOUT)

        assert [(cls, scope) for cls, scope, _ in store.apply_calls] == [(_AlphaActor, "P")]


##
## 33-3 AC #5 — resolve_state_type
##
class TestResolveStateType:
    """The declared state type, or ``None`` rather than a guess."""

    def test_direct_binding(self) -> None:
        assert resolve_state_type(_AlphaActor) is _AlphaState
        assert resolve_state_type(_BetaActor) is _BetaState

    def test_subclass_finds_it_up_the_mro(self) -> None:
        assert resolve_state_type(_DerivedAlphaActor) is _AlphaState

    def test_a_base_state_binding_answers_base_state(self) -> None:
        # ResourceHost, UserProxy and Orchestrator are all Akgent[BaseConfig, BaseState].
        assert resolve_state_type(ResourceHost) is BaseState
        assert resolve_state_type(Orchestrator) is BaseState

    def test_unparameterised_answers_none(self) -> None:
        assert resolve_state_type(_UnparameterisedActor) is None

    def test_a_none_state_argument_answers_none(self) -> None:
        assert resolve_state_type(_NoStateActor) is None

    def test_a_non_akgent_class_answers_none(self) -> None:
        assert resolve_state_type(cast(Any, _AlphaState)) is None
        assert resolve_state_type(cast(Any, BaseConfig)) is None

    def test_it_answers_the_state_not_the_config(self) -> None:
        # The distinguishing case: both type arguments are concrete and different, so a
        # resolver reading position 0 would answer _RichConfig here and pass every other
        # row in this class.
        assert resolve_state_type(_RichAlphaActor) is _AlphaState
        assert resolve_state_type(_RichAlphaActor) is not _RichConfig

    def test_the_answer_is_memoised_and_repeatable(self) -> None:
        assert resolve_state_type(_AlphaActor) is resolve_state_type(_AlphaActor)
        assert resolve_state_type(_UnparameterisedActor) is None
        assert resolve_state_type(_UnparameterisedActor) is None


##
## 33-3 AC #7 — the cold host is unchanged in shape
##
class TestColdHostUnchangedByTheClassCarryingSignature:
    """No store registered: creation still works and a registered scope's delta is a no-op."""

    def test_cold_host_creates_and_absorbs_a_delta_silently(
        self, host: ActorAddress, caplog: pytest.LogCaptureFixture
    ) -> None:
        address = _get_or_create_kind(host, _AlphaActor, "P")
        assert address.is_alive()

        with caplog.at_level(logging.WARNING, logger=HOST_LOGGER):
            _proxy(host).notify_delta("P", StateDelta(set={"alpha": "x"})).get(timeout=TIMEOUT)

        assert host.is_alive()
        assert _host_records(caplog) == []
