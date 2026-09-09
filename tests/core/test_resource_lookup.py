"""Tests for the registry lookup, the orchestrator's forward, and the attach event.

Three things ship here: ``ActorSystem.find_by_class``, ``Orchestrator.getResourceOrCreate``
and the rule that the caller's own attach event rides ``EventMessage`` unread. The lookup
is what lets a card reach a resource whose lifetime outlives its team, and — the half
story 33-1 could not reach — what lets a hosted actor, which has no orchestrator and no
parent, find its way back to the host that started it.

The lookup matches the **exact** class. Each resource kind subclasses ``ResourceHost`` and
one host of each concrete class runs per process, so a subclass-inclusive answer would
return another kind's host: the forward would refuse "found two" while exactly one host
of the asked class runs, or a hosted actor's route home would land its delta in another
kind's registry. The two-host specs below run a base host and a subclass host **at
once**, because a single-class test cannot tell exact-type from ``issubclass``.

``_host_address`` below is the **reference shape** the tool slice copies. It looks the
host up at each use and never caches an address, and it treats an empty answer as
"nothing to tell" rather than an error. Both rules are load-bearing and both are
exercised by specs in this module.

Assertions go through an actor's own methods wherever one answers the question. One
structural fact does not — the orchestrator's ``_children`` — because a pykka proxy
refuses any name starting with an underscore, so that single assertion reads the live
actor through ``_actor_of``. Reaching an ``ActorAddressImpl``'s ``_actor_ref`` for a
proxy is the same kind of reach, one level shallower. Both are legal here and only
here: core owns the actor implementation.
"""

from __future__ import annotations

import inspect
import logging
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, ClassVar, cast

import pykka
import pytest

from akgentic.core.actor_address import ActorAddress
from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent, WarningError
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message, ResourceStopped
from akgentic.core.messages.orchestrator import (
    EventMessage,
    StartMessage,
    StopMessage,
)
from akgentic.core.orchestrator import Orchestrator
from akgentic.core.resource_host import ResourceHost, StateDelta
from akgentic.core.utils.deserializer import deserialize_object

HOST_LOGGER = "akgentic.core.resource_host"
TIMEOUT = 10.0

# The blocking ask a hosted actor makes back into the host in TestCycleGuard. Bounded so
# a re-introduced cycle fails in ~2 s rather than parking a thread until the suite's
# 300 s per-test timeout. It is deliberate test pressure, not a recommended shape.
CALLBACK_TIMEOUT = 2


@dataclass(frozen=True)
class _ProbeAttached:
    """The attach event a binding package would declare, as this module's stand-in.

    At **module top level** on purpose: the serializer persists a dataclass under
    ``f"{cls.__module__}.{cls.__name__}"`` — ``__name__``, not ``__qualname__`` — so a
    class nested in a test class or a function would serialise to a path that does not
    exist and the round-trip half of the event spec could not be written. That is the
    rule the tool slice's own event must follow, and this probe demonstrates it.
    """

    agent_id: uuid.UUID
    probe: str = "sentinel"


##
## Helpers
##
def _proxy(address: ActorAddress) -> pykka.ActorProxy[Any]:
    """A pykka proxy onto the actor behind *address*, for calling its own methods."""
    return cast(ActorAddressImpl, address)._actor_ref.proxy()


def _actor_of(address: ActorAddress) -> Akgent[Any, Any]:
    """The live actor behind an address; legal here because core owns the actor impl."""
    actor = cast(ActorAddressImpl, address)._actor_ref._actor_weakref()
    assert actor is not None, "actor was garbage collected"
    return cast("Akgent[Any, Any]", actor)


def _flush(address: ActorAddress) -> None:
    """Block until everything already queued for *address* has been handled.

    One FIFO mailbox serves messages, proxy calls and attribute reads alike, so an
    attribute read that has resolved proves every earlier envelope was processed.
    """
    _proxy(address).config.get(timeout=TIMEOUT)


def _wait_until_stopped(address: ActorAddress, timeout: float = 5.0) -> bool:
    """Poll until *address* reports stopped, or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not address.is_alive():
            return True
        time.sleep(0.01)
    return False


def _stop_and_wait(address: ActorAddress) -> None:
    """Stop the actor behind *address* gracefully and wait for it to be gone."""
    cast(ActorAddressImpl, address)._actor_ref.stop(block=True)
    assert _wait_until_stopped(address)


def _host_of(
    system: ActorSystem,
    name: str = "#ResourceHost",
    host_class: type[ResourceHost] = ResourceHost,
) -> ActorAddress:
    """Start a host the way wiring code does: explicitly, once per concrete class."""
    return system.createActor(host_class, config=BaseConfig(name=name, role="ResourceHost"))


def _ask_host(
    system: ActorSystem,
    host: ActorAddress,
    actor_class: type[Akgent[Any, Any]],
    name: str,
    timeout: float = TIMEOUT,
) -> ActorAddress:
    """Ask the host directly for the resource named *name*, bypassing any orchestrator."""
    return system.proxy_ask(host, ResourceHost, timeout=timeout).getResourceOrCreate(
        actor_class, BaseConfig(name=name)
    )


def _probe() -> _ProbeAttached:
    """A fresh attach event, as a binding site would build one."""
    return _ProbeAttached(agent_id=uuid.uuid4())


def _forward(
    orchestrator: ActorAddress,
    actor_class: type[Akgent[Any, Any]],
    name: str,
    event: Any,
    host_class: type[ResourceHost] = ResourceHost,
) -> ActorAddress:
    """Call the orchestrator's forward through its proxy and wait for the answer."""
    future = _proxy(orchestrator).getResourceOrCreate(
        host_class, actor_class, BaseConfig(name=name), event
    )
    return cast(ActorAddress, future.get(timeout=TIMEOUT))


def _messages(orchestrator: ActorAddress, message_type: type | None = None) -> list[Message]:
    """The orchestrator's own message stream, optionally filtered by type."""
    return cast(
        "list[Message]",
        _proxy(orchestrator).get_messages(None, message_type).get(timeout=TIMEOUT),
    )


def _attach_events(messages: list[Message]) -> list[EventMessage]:
    """The ``EventMessage``s among *messages* whose payload is a ``_ProbeAttached``.

    Keyed on the payload, never on the envelope: ``EventMessage`` carries every domain
    event, so the envelope's type alone identifies nothing.
    """
    return [
        msg
        for msg in messages
        if isinstance(msg, EventMessage) and isinstance(msg.event, _ProbeAttached)
    ]


def _attached(orchestrator: ActorAddress) -> list[EventMessage]:
    """Every attach event on the orchestrator's own stream."""
    return _attach_events(_messages(orchestrator, EventMessage))


def _host_records(caplog: pytest.LogCaptureFixture, level: int = logging.INFO) -> list[str]:
    """Messages emitted by the host's own logger at *level* or above."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == HOST_LOGGER and record.levelno >= level
    ]


def _host_address() -> ActorAddress | None:
    """The process's resource host, looked up at each use and never cached.

    The reference shape for every hosted actor, in this package and outside it. A
    hosted actor names the host class its kind is hosted by; the lookup is exact, so
    only the base runs in every test that uses this.

    Never cached: a cached address survives a host that went away, and a proxy onto a
    dead actor turns a lost delta into silence rather than into an error. An empty
    answer is not a failure either — at process shutdown the host may already be gone,
    and a hosted actor that raised there would only make teardown noisier.
    """
    hosts = ActorSystem.find_by_class(ResourceHost)
    return hosts[0] if hosts else None


##
## Test doubles
##
class _HostedState(BaseState):
    """State of the hosted actors used throughout this module."""

    value: str = "default"


class _CountingActor(Akgent[BaseConfig, _HostedState]):
    """Hosted actor recording each construction, so a hit and a miss are separable."""

    constructions: ClassVar[list[uuid.UUID]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = _HostedState()
        _CountingActor.constructions.append(self.agent_id)

    def ping(self) -> str:
        """A method a caller can reach through a proxy, to prove the address works."""
        return "pong"


class _AnnouncingActor(Akgent[BaseConfig, _HostedState]):
    """The reference hosted actor: it tells its host, through the lookup, that it stopped.

    The lookup runs inside ``on_stop``, in this actor's own thread, with no orchestrator
    to ask and no parent to walk up to. That is the whole point of the spec it serves.
    """

    announced: ClassVar[list[str]] = []
    stops: ClassVar[list[str]] = []

    def on_stop(self) -> None:
        host = _host_address()
        if host is not None:
            self.send(host, ResourceStopped(scope=self.config.name))
            _AnnouncingActor.announced.append(self.config.name)
        # Recorded whether or not a host was found: an empty lookup is not an error, and
        # this is what proves the actor stopped cleanly through that branch.
        _AnnouncingActor.stops.append(self.config.name)
        super().on_stop()


class _SilentActor(Akgent[BaseConfig, _HostedState]):
    """A hosted actor that announces nothing — the control for the announcement spec.

    Without it the host's "entry dropped" record could be produced by anything at all;
    with it, the record is proof that the announcement, and therefore the lookup, worked.
    """


class _UnbuildableActor(Akgent[BaseConfig, _HostedState]):
    """A hosted actor that cannot be constructed, so the host's call raises.

    The only way, from outside the host, to make a forward fail *after* it has found
    exactly one host. It is what turns "one event per **successful** forward" into a
    falsifiable claim rather than a word in a docstring.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        raise RuntimeError("this resource cannot be built")


class _CallbackActor(Akgent[BaseConfig, _HostedState]):
    """A hosted actor that asks its host back, blocking, from ``init_state``.

    This is the cycle story 33-1 could not construct. The host delivers ``init_state``
    with ``proxy_tell`` and is therefore free to answer; swap that for ``proxy_ask`` and
    the two threads wait on each other. The ask is bounded so the failure is fast.
    """

    callbacks: ClassVar[list[str]] = []

    def init_state(self, state: _HostedState) -> None:
        host = _host_address()
        if host is not None:
            self.proxy_ask(host, ResourceHost, timeout=CALLBACK_TIMEOUT).notify_delta(
                self.config.name, StateDelta(set={"callback": True})
            )
            _CallbackActor.callbacks.append(self.config.name)
        super().init_state(state)


class _NeverStarted(Akgent[BaseConfig, _HostedState]):
    """An Akgent subclass that no test ever starts, so its lookup is always empty."""


class _SubHost(ResourceHost):
    """A second resource kind's host, as a binding package declares one."""


def _make_impostor_host_class() -> type[Akgent[Any, Any]]:
    """A class whose ``__name__`` is literally ``ResourceHost`` and which is not one.

    Defined inside a function so the real ``ResourceHost`` imported at module level stays
    usable. A name match would return this actor; a class match cannot.
    """

    class ResourceHost(Akgent[BaseConfig, _HostedState]):  # noqa: N801
        pass

    return ResourceHost


_ImpostorHost = _make_impostor_host_class()


class _FakeStore:
    """Records every call and returns whatever state it was seeded with."""

    def __init__(self, state: BaseState | None = None) -> None:
        self.state = state
        self.load_calls: list[tuple[type[Akgent[Any, Any]], str]] = []
        self.apply_calls: list[tuple[type[Akgent[Any, Any]], str, StateDelta]] = []

    def load(self, actor_class: type[Akgent[Any, Any]], scope: str) -> BaseState | None:
        self.load_calls.append((actor_class, scope))
        return self.state

    def apply(self, actor_class: type[Akgent[Any, Any]], scope: str, delta: StateDelta) -> None:
        self.apply_calls.append((actor_class, scope, delta))


class _RecordingSubscriber:
    """An EventSubscriber that keeps every message the orchestrator fans out to it."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def on_message(self, message: Message) -> None:
        self.messages.append(message)


##
## Fixtures
##
@pytest.fixture(autouse=True)
def reset_class_state() -> Generator[None, None, None]:
    """Clear every class-level ledger and stop any actor a test leaked.

    The pykka registry is process-global, and this module's whole subject is a lookup
    over it: one leaked host makes a later "no host" spec fail in a different file.
    """
    _CountingActor.constructions.clear()
    _AnnouncingActor.announced.clear()
    _AnnouncingActor.stops.clear()
    _CallbackActor.callbacks.clear()
    yield
    _CountingActor.constructions.clear()
    _AnnouncingActor.announced.clear()
    _AnnouncingActor.stops.clear()
    _CallbackActor.callbacks.clear()
    pykka.ActorRegistry.stop_all()


@pytest.fixture
def system() -> Generator[ActorSystem, None, None]:
    """A live actor system, torn down after each test."""
    actor_system = ActorSystem()
    yield actor_system
    actor_system.shutdown()


@pytest.fixture
def host(system: ActorSystem) -> ActorAddress:
    """A base ResourceHost with no store registered — cold, as a fresh process is."""
    return _host_of(system)


@pytest.fixture
def sub_host(system: ActorSystem) -> ActorAddress:
    """A ``_SubHost`` — a second kind's host, running beside the base."""
    return _host_of(system, "#SubHost", _SubHost)


@pytest.fixture
def orchestrator(system: ActorSystem) -> ActorAddress:
    """A live Orchestrator, the caller of the forward."""
    return system.createActor(
        Orchestrator, config=BaseConfig(name="#Orchestrator", role="Orchestrator")
    )


##
## The lookup is static, typed, and returns usable public addresses
##
class TestFindByClass:
    """Callable on the class, answering public addresses that work straight away."""

    def test_returns_usable_public_addresses(self, system: ActorSystem, host: ActorAddress) -> None:
        found = ActorSystem.find_by_class(ResourceHost)

        assert len(found) == 1
        address = found[0]
        assert isinstance(address, ActorAddress)
        assert not isinstance(address, pykka.ActorRef)
        assert address.agent_id == host.agent_id
        assert address.is_alive()

        # Usable straight away, through the public proxy seam and nothing else.
        hosted = system.proxy_ask(address, ResourceHost, timeout=TIMEOUT).getResourceOrCreate(
            _CountingActor, BaseConfig(name="#Resource-usable")
        )
        assert hosted.is_alive()
        assert system.proxy_ask(hosted, _CountingActor, timeout=TIMEOUT).ping() == "pong"

    def test_no_actor_of_that_class_answers_an_empty_list(self) -> None:
        # No fixture, no instance, no live ActorSystem: the lookup is static and this
        # call is the proof. An empty answer is a list, never None and never a raise.
        found = ActorSystem.find_by_class(_NeverStarted)

        assert found == []
        assert isinstance(found, list)


##
## AC #1 — matching is by the exact class: not a subclass, and not a class name
##
class TestMatchingIsByExactClass:
    """Each class answers its own host; a colliding ``__name__`` answers nothing."""

    def test_a_base_and_a_subclass_host_each_answer_their_own(
        self, host: ActorAddress, sub_host: ActorAddress
    ) -> None:
        # The premise of the spec. If either of these ever stops holding, the assertions
        # below stop meaning what they claim and must be rewritten, not relaxed.
        assert issubclass(_SubHost, ResourceHost)
        assert _SubHost is not ResourceHost
        assert host.agent_id != sub_host.agent_id

        # pykka's own lookup is subclass-inclusive and answers BOTH. Asserted here so the
        # spec records that the narrowing below is core's, not the registry's — without
        # it, "the base answers one" would also pass against a registry that had simply
        # never seen the sub-host.
        assert len(pykka.ActorRegistry.get_by_class(ResourceHost)) == 2

        base_ids = [address.agent_id for address in ActorSystem.find_by_class(ResourceHost)]
        sub_ids = [address.agent_id for address in ActorSystem.find_by_class(_SubHost)]

        assert base_ids == [host.agent_id]
        assert sub_ids == [sub_host.agent_id]

    def test_an_unrelated_class_with_the_same_name_is_not_found(
        self, system: ActorSystem, host: ActorAddress
    ) -> None:
        # The premise of the spec. If either of these ever stops holding, the assertions
        # below stop meaning what they claim and must be rewritten, not relaxed.
        assert _ImpostorHost.__name__ == "ResourceHost"
        assert not issubclass(_ImpostorHost, ResourceHost)

        impostor = system.createActor(
            _ImpostorHost, config=BaseConfig(name="#Impostor", role="ResourceHost")
        )

        found_ids = {address.agent_id for address in ActorSystem.find_by_class(ResourceHost)}

        # The real host is the control: without it, "impostor not found" would also be
        # satisfied by a lookup that found nothing at all.
        assert host.agent_id in found_ids
        assert impostor.agent_id not in found_ids


##
## Only live actors are returned, and the honesty clause
##
class TestLivenessFilter:
    """A stopped host is not returned — and the registry, not the filter, is why."""

    def test_a_stopped_host_is_not_returned(self, system: ActorSystem, host: ActorAddress) -> None:
        assert len(ActorSystem.find_by_class(ResourceHost)) == 1

        _stop_and_wait(host)

        assert ActorSystem.find_by_class(ResourceHost) == []
        # The experiment 33-2 asked for, recorded as an assertion rather than a claim:
        # the stopped host has already left the registry, so the ``is_alive()`` filter
        # never sees it. The filter is therefore NON-LOAD-BEARING against the installed
        # pykka — ``Actor._stop`` unregisters before it sets the stopped flag — and
        # deleting it leaves this module green. It is kept for the day that changes.
        assert pykka.ActorRegistry.get_by_class(ResourceHost) == []


##
## A hosted actor reaches its host through the same lookup
##
class TestHostedActorReachesItsHost:
    """The lookup runs in the hosted actor's own thread, and an empty answer is fine."""

    def test_a_hosted_actor_announces_its_stop_through_the_lookup(
        self, system: ActorSystem, host: ActorAddress, caplog: pytest.LogCaptureFixture
    ) -> None:
        announcing = _ask_host(system, host, _AnnouncingActor, "#Resource-announce")
        silent = _ask_host(system, host, _SilentActor, "#Resource-silent")

        with caplog.at_level(logging.INFO, logger=HOST_LOGGER):
            _stop_and_wait(announcing)
            _stop_and_wait(silent)
            _flush(host)

        records = _host_records(caplog)
        assert _AnnouncingActor.announced == ["#Resource-announce"]
        assert any(
            "registry entry dropped" in record and "#Resource-announce" in record
            for record in records
        )
        # The control. The silent actor stopped exactly the same way and said nothing,
        # so its scope must produce no record at all. Without this, the assertion above
        # would be satisfied by a host that dropped entries for its own reasons.
        assert not any("#Resource-silent" in record for record in records)

        # And the consequence the announcement buys: the entry is gone, so the next
        # get-or-create builds a new actor.
        replacement = _ask_host(system, host, _AnnouncingActor, "#Resource-announce")
        assert replacement.agent_id != announcing.agent_id
        assert replacement.is_alive()

    def test_an_empty_lookup_is_not_an_error(self, system: ActorSystem, host: ActorAddress) -> None:
        address = _ask_host(system, host, _AnnouncingActor, "#Resource-orphaned")

        # The host goes first, as it may at process shutdown.
        _stop_and_wait(host)
        assert _host_address() is None

        _stop_and_wait(address)

        # It stopped, and it did so without announcing and without raising.
        assert _AnnouncingActor.stops == ["#Resource-orphaned"]
        assert _AnnouncingActor.announced == []


##
## The forward returns what the host returns
##
class TestForward:
    """One resource per name, across agents and across teams in one process."""

    def test_two_agents_in_one_team_get_one_actor(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        first = _forward(orchestrator, _CountingActor, "#Resource-shared", _probe())
        second = _forward(orchestrator, _CountingActor, "#Resource-shared", _probe())

        assert first.agent_id == second.agent_id
        assert len(_CountingActor.constructions) == 1
        assert first.is_alive()

    def test_two_orchestrators_get_the_same_one_actor(
        self, system: ActorSystem, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        other = system.createActor(
            Orchestrator, config=BaseConfig(name="#Orchestrator-2", role="Orchestrator")
        )
        assert other.team_id != orchestrator.team_id

        first = _forward(orchestrator, _CountingActor, "#Resource-crossteam", _probe())
        second = _forward(other, _CountingActor, "#Resource-crossteam", _probe())

        assert first.agent_id == second.agent_id
        assert len(_CountingActor.constructions) == 1


##
## AC #2, #3 — one host per concrete class, and each forward reaches its own
##
class TestOneHostPerKind:
    """Two kinds are two hosts and two registries; the forward never crosses them.

    Both hosts run at once in every spec here. That is the trap the epic names: with
    the base alone, or the sub alone, an ``issubclass`` lookup and an exact one give the
    same answers, and a guard that started them in separate tests would pass against
    the very defect it exists to catch.
    """

    def test_each_forward_reaches_its_own_host(
        self, host: ActorAddress, sub_host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        assert issubclass(_SubHost, ResourceHost)
        assert _SubHost is not ResourceHost

        # The SAME name through each host. With a subclass-inclusive lookup the first
        # forward finds two hosts and refuses "Found 2"; with an exact one each host
        # hosts its own actor under that name — one registry per host is the silo.
        on_base = _forward(orchestrator, _CountingActor, "#Resource-kind", _probe())
        on_sub = _forward(
            orchestrator, _CountingActor, "#Resource-kind", _probe(), host_class=_SubHost
        )

        assert on_base.is_alive()
        assert on_sub.is_alive()
        assert on_base.agent_id != on_sub.agent_id
        assert len(_CountingActor.constructions) == 2

        # Repeats are hits, each on its own host.
        assert _forward(orchestrator, _CountingActor, "#Resource-kind", _probe()).agent_id == (
            on_base.agent_id
        )
        assert _forward(
            orchestrator, _CountingActor, "#Resource-kind", _probe(), host_class=_SubHost
        ).agent_id == (on_sub.agent_id)
        assert len(_CountingActor.constructions) == 2

        # Prove the routing rather than infer it from ids. Stop the sub-host's actor:
        # the sub-host's next answer is a NEW actor, and the base's is still its original.
        # A forward that reached the base host regardless of host_class would answer the
        # base's actor for both and construct nothing here.
        _stop_and_wait(on_sub)
        replacement = _forward(
            orchestrator, _CountingActor, "#Resource-kind", _probe(), host_class=_SubHost
        )
        assert replacement.agent_id != on_sub.agent_id
        assert replacement.is_alive()
        assert len(_CountingActor.constructions) == 3
        assert _forward(orchestrator, _CountingActor, "#Resource-kind", _probe()).agent_id == (
            on_base.agent_id
        )
        assert len(_CountingActor.constructions) == 3

    def test_only_a_host_of_the_asked_class_counts(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        # Only the base runs. Asking for the sub is asking for a kind with no host.
        assert ActorSystem.find_by_class(_SubHost) == []
        subscriber = _RecordingSubscriber()
        _proxy(orchestrator).subscribe(subscriber).get(timeout=TIMEOUT)

        with pytest.raises(RuntimeError) as excinfo:
            _forward(orchestrator, _CountingActor, "#Resource-nosub", _probe(), host_class=_SubHost)

        message = str(excinfo.value)
        assert "No _SubHost is running" in message
        assert "wiring time" in message
        assert not isinstance(excinfo.value, WarningError)

        # Refused loudly, and nothing conjured to make the refusal go away: no actor on
        # the base host, no sub-host, no event.
        assert _CountingActor.constructions == []
        assert ActorSystem.find_by_class(_SubHost) == []
        assert _attached(orchestrator) == []
        assert _attach_events(subscriber.messages) == []


##
## A process with no host fails the first bind, and creates nothing
##
class TestNoHost:
    """A clear refusal a wiring author can act on, and no host conjured to fix it."""

    def test_the_first_bind_raises_and_creates_nothing(self, orchestrator: ActorAddress) -> None:
        assert ActorSystem.find_by_class(ResourceHost) == []

        with pytest.raises(RuntimeError) as excinfo:
            _forward(orchestrator, _CountingActor, "#Resource-nohost", _probe())

        message = str(excinfo.value)
        assert "No ResourceHost is running" in message
        assert "wiring time" in message
        # Not a WarningError: that class means "handled already, non-critical" and is
        # reported as a WarningMessage. A process that cannot bind a resource at all is
        # not a warning.
        assert not isinstance(excinfo.value, WarningError)

        # The forward must never create the host its error asks for.
        assert ActorSystem.find_by_class(ResourceHost) == []
        assert _CountingActor.constructions == []


##
## Two hosts OF ONE CLASS in one process is refused, not silently resolved
##
class TestTwoHosts:
    """Picking the first would let two teams land two actors on one resource."""

    def test_more_than_one_host_raises_and_creates_nothing(
        self, system: ActorSystem, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        second_host = _host_of(system, "#ResourceHost-2")
        assert len({host.agent_id, second_host.agent_id}) == 2
        assert len(ActorSystem.find_by_class(ResourceHost)) == 2

        with pytest.raises(RuntimeError) as excinfo:
            _forward(orchestrator, _CountingActor, "#Resource-twohosts", _probe())

        message = str(excinfo.value)
        assert "Found 2 ResourceHost actors" in message
        assert "exactly one" in message
        assert _CountingActor.constructions == []

    def test_the_lookup_itself_does_not_refuse(
        self, system: ActorSystem, host: ActorAddress
    ) -> None:
        _host_of(system, "#ResourceHost-2")

        # The refusal belongs to the forward, which knows it needs exactly one. The
        # lookup reports what is there.
        assert len(ActorSystem.find_by_class(ResourceHost)) == 2


##
## AC #4, #5, #6 — the caller's event, carried by identity, one per successful forward
##
class TestAttachEvent:
    """The orchestrator wraps the caller's object in ``EventMessage`` and reads nothing."""

    def test_the_stream_holds_the_callers_object_by_identity(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        payload = _probe()

        _forward(orchestrator, _CountingActor, "#Resource-event", payload)

        events = _attached(orchestrator)
        assert len(events) == 1
        message = events[0]
        # Identity, not equality. A copy, a rebuild or a re-validation of the payload
        # compares EQUAL to the original and would pass ``==``; only ``is`` records that
        # core carried the caller's object and did nothing to it.
        assert message.event is payload
        # What core does do — the whole of it — is ``Message.init`` on the envelope.
        assert message.team_id == orchestrator.team_id
        assert message.sender is not None
        assert message.sender.agent_id == orchestrator.agent_id

    def test_a_subscriber_receives_the_same_object(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        subscriber = _RecordingSubscriber()
        _proxy(orchestrator).subscribe(subscriber).get(timeout=TIMEOUT)
        payload = _probe()

        _forward(orchestrator, _CountingActor, "#Resource-subscribed", payload)

        # The fan-out snapshots the ENVELOPE (its live sender becomes a proxy) and leaves
        # a non-model payload untouched, so the identity survives to the subscriber.
        received = _attach_events(subscriber.messages)
        assert len(received) == 1
        assert received[0].event is payload
        assert received[0].team_id == orchestrator.team_id

    def test_the_payload_round_trips_under_its_own_import_path(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        payload = _probe()
        _forward(orchestrator, _CountingActor, "#Resource-roundtrip", payload)
        message = _attached(orchestrator)[0]

        dumped = message.model_dump()
        restored = deserialize_object(dumped)

        # Equality on purpose here, and only here: a deserialised object is never the
        # same object. What this pins is that the payload persisted under its own
        # ``module.ClassName`` and came back as itself — which is how a client reads
        # the kind by name, with no kind string and no base class in core.
        assert isinstance(restored, EventMessage)
        assert isinstance(restored.event, _ProbeAttached)
        assert restored.event == payload
        assert restored.event is not payload
        assert restored.team_id == orchestrator.team_id

    def test_two_agents_binding_one_resource_emit_two_events_and_build_one_actor(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        first_payload = _probe()
        second_payload = _probe()

        first = _forward(orchestrator, _CountingActor, "#Resource-two", first_payload)
        second = _forward(orchestrator, _CountingActor, "#Resource-two", second_payload)

        # One actor: the second call was a registry hit.
        assert first.agent_id == second.agent_id
        assert len(_CountingActor.constructions) == 1

        # Two events all the same. The forward cannot tell a hit from a miss and must
        # not learn: the event records which agent bound, not what the host did.
        events = _attached(orchestrator)
        assert [event.event for event in events] == [first_payload, second_payload]
        assert events[0].event is first_payload
        assert events[1].event is second_payload

    def test_core_keeps_no_attach_message_class(self) -> None:
        import akgentic.core
        import akgentic.core.messages

        with pytest.raises(ImportError):
            from akgentic.core.messages import ResourceAttached  # noqa: F401

        assert "ResourceAttached" not in akgentic.core.messages.__all__
        assert "ResourceAttached" not in akgentic.core.__all__

    def test_the_forward_takes_the_host_class_and_the_event_and_nothing_workspace_shaped(
        self,
    ) -> None:
        parameters = inspect.signature(Orchestrator.getResourceOrCreate).parameters

        assert list(parameters) == ["self", "host_class", "actor_class", "config", "event"]
        assert "agent_id" not in parameters
        assert "workspace_path" not in parameters
        assert "metadata_keys" not in parameters


##
## AC #6 — no event on a refusal
##
class TestNoEventOnRefusal:
    """Neither refusal reaches the stream, and neither reaches a subscriber."""

    def test_a_no_host_refusal_emits_nothing(self, orchestrator: ActorAddress) -> None:
        subscriber = _RecordingSubscriber()
        _proxy(orchestrator).subscribe(subscriber).get(timeout=TIMEOUT)

        with pytest.raises(RuntimeError):
            _forward(orchestrator, _CountingActor, "#Resource-nohost", _probe())

        assert _attached(orchestrator) == []
        assert _attach_events(subscriber.messages) == []

    def test_a_two_host_refusal_emits_nothing(
        self, system: ActorSystem, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        _host_of(system, "#ResourceHost-2")
        subscriber = _RecordingSubscriber()
        _proxy(orchestrator).subscribe(subscriber).get(timeout=TIMEOUT)

        with pytest.raises(RuntimeError):
            _forward(orchestrator, _CountingActor, "#Resource-twohosts", _probe())

        assert _attached(orchestrator) == []
        assert _attach_events(subscriber.messages) == []

    def test_a_failed_host_call_emits_nothing(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        # Beyond the two refusals, and deliberately so. The rule is "one event per
        # SUCCESSFUL forward"; with one host running and the host call itself failing,
        # only this spec separates emitting after the answer from emitting before it.
        # Without it, moving the emit above the ask leaves the suite green.
        subscriber = _RecordingSubscriber()
        _proxy(orchestrator).subscribe(subscriber).get(timeout=TIMEOUT)

        with pytest.raises(RuntimeError, match="cannot be built"):
            _forward(orchestrator, _UnbuildableActor, "#Resource-unbuildable", _probe())

        assert _attached(orchestrator) == []
        assert _attach_events(subscriber.messages) == []


##
## A hosted actor is not a team actor, and the forward does not make it one
##
class TestHostedActorIsNotATeamActor:
    """The forward binds; it does not adopt."""

    def test_the_forward_adds_nobody_to_the_team(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        hosted = _forward(orchestrator, _CountingActor, "#Resource-unowned", _probe())

        # A control the orchestrator *does* own. Without it every negative below is
        # vacuous: an orchestrator that saw nothing at all would satisfy them too.
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
        assert hosted.agent_id not in roster_ids

        start_senders = {
            msg.sender.agent_id for msg in _messages(orchestrator, StartMessage) if msg.sender
        }
        assert control.agent_id in start_senders
        assert hosted.agent_id not in start_senders

        # Nothing at all on this stream was sent by the hosted actor; the only message
        # that mentions the resource is the orchestrator's own attach event.
        assert not any(
            msg.sender is not None and msg.sender.agent_id == hosted.agent_id
            for msg in _messages(orchestrator)
        )
        assert len(_attached(orchestrator)) == 1

        assert _proxy(hosted).orchestrator.get(timeout=TIMEOUT) is None
        children_ids = {child.agent_id for child in _actor_of(orchestrator)._children}
        assert control.agent_id in children_ids
        assert hosted.agent_id not in children_ids

        # The StopMessage half, asserted last and against a control, because asserting
        # it while both actors are still running proves nothing: the list is empty then
        # whatever the forward did. Stopping both makes it a difference. ``on_stop``
        # notifies through ``_notify_orchestrator``, which is a no-op with no
        # orchestrator, so the team member's stop lands here and the hosted actor's does
        # not — and an implementation that adopted the hosted actor would announce it.
        _stop_and_wait(hosted)
        _stop_and_wait(control)
        _flush(orchestrator)

        stop_senders = {
            msg.sender.agent_id for msg in _messages(orchestrator, StopMessage) if msg.sender
        }
        assert control.agent_id in stop_senders
        assert hosted.agent_id not in stop_senders

    def test_a_hosted_actor_asking_for_a_team_is_a_bug_by_construction(
        self, host: ActorAddress, orchestrator: ActorAddress
    ) -> None:
        hosted = _forward(orchestrator, _CountingActor, "#Resource-noteam", _probe())

        with pytest.raises(WarningError):
            _proxy(hosted).get_team().get(timeout=TIMEOUT)


##
## The cycle guard
##
class TestCycleGuard:
    """A hosted actor calling back into the host from ``init_state`` must not wedge.

    Under the shipped ``proxy_tell`` delivery the host is free, the callback is answered
    and everything below holds. Under ``proxy_ask`` the host waits on ``init_state``
    while ``init_state`` waits on the host: the inner ask times out in ~2 s, pykka sets
    that on the host's pending future, and the call below raises instead of returning an
    address. Fast red, no wedged actor left for teardown.
    """

    def test_a_blocking_callback_from_init_state_does_not_wedge_the_host(
        self, system: ActorSystem, host: ActorAddress
    ) -> None:
        store = _FakeStore(_HostedState(value="restored"))
        system.proxy_ask(host, ResourceHost, timeout=TIMEOUT).register_store(store)

        address = _ask_host(system, host, _CallbackActor, "#Resource-callback")

        assert address.is_alive()
        _flush(address)
        assert _CallbackActor.callbacks == ["#Resource-callback"]
        # The delta is written, not dropped: ``getResourceOrCreate`` records the registry
        # entry before the host can dequeue the callback, so the scope is known by then.
        assert [(cls, scope) for cls, scope, _ in store.apply_calls] == [
            (_CallbackActor, "#Resource-callback")
        ]
        assert store.apply_calls[0][2].set == {"callback": True}
