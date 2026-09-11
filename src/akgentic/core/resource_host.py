"""The resource host: get-or-create keyed by name, and persistence through a Protocol.

The host has exactly two jobs and deliberately no third one (ADR-022 §Decision 2):

1. **Get-or-create keyed by name.** :meth:`ResourceHost.getResourceOrCreate` returns the
   one live actor registered under ``config.name``, creating it on a miss. The work runs
   on the host's own mailbox, which *is* the serialisation: two callers resolving the same
   name at the same moment cannot both create. There is no lock and no double check.
2. **Persistence through a Protocol.** A :class:`ResourceStore` — implemented outside core,
   never here — restores a hosted actor's state on a miss and absorbs the :class:`StateDelta`
   it reports afterwards. Until :meth:`ResourceHost.register_store` is called the host runs
   *cold*: ``load`` answers ``None`` and the write-back is a no-op. The flow is otherwise
   identical, so a deployment with no store is a supported deployment, not a degraded one.

The host is not an ``Orchestrator``. It carries no team routing, holds nothing beyond the
registry and the store handle, and never touches a hosted actor's lifetime: a hosted actor
is nobody's child, outlives every team that reaches it, and is stopped by the actor system
at shutdown like any other root actor.

The host hosts *any* ``Akgent`` subclass under *any* name. It knows nothing about what the
name means — no paths, no parsing, no per-domain branch. A line here that would read
differently for one kind of resource than another belongs in another package.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, override, runtime_checkable

from pydantic import JsonValue

from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.agent import Akgent
from akgentic.core.agent_card import _extract_state_type
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.utils.serializer import SerializableBaseModel

if TYPE_CHECKING:
    from akgentic.core.actor_address import ActorAddress
    from akgentic.core.messages.message import ResourceStopped

logger = logging.getLogger(__name__)


def resolve_state_type(actor_class: type[Akgent[Any, Any]]) -> type[BaseState] | None:
    """The concrete state type *actor_class* declares, for a store to rebuild into.

    A :class:`ResourceStore` is handed the resource's actor class and a document
    assembled from :class:`StateDelta` keys. That document is a plain nested dict with
    **no root type marker** — unlike a whole serialised model, which core's
    ``deserialize_object`` rebuilds from a ``__model__`` marker, a delta-assembled
    document cannot say what it is. The class is the only registry-free route from the
    document back to a concrete state class, and this function is that route. Core
    exposes it so no store has to reimplement the ``__orig_bases__`` walk — the coupling
    the Protocol exists to remove, reappearing one level down.

    The answer is the **declared** type argument, so a store rebuilding through it
    produces the declared class and never a subclass of it.

    ``None`` means core cannot name a concrete state class for this actor — an
    unparameterised ``Akgent`` subclass, a binding whose state argument is not a
    :class:`BaseState` subclass (``Akgent[BaseConfig, None]`` is a real shape), or a
    class that is not an ``Akgent`` at all. A store that gets ``None`` should answer
    ``None`` from :meth:`ResourceStore.load` rather than substituting ``BaseState``,
    which would hand the actor an empty state of the wrong class.

    The host itself never calls this. It never builds a state; it passes whatever the
    store returns straight to ``init_state``. A host that started deriving state types
    would be doing the store's job.

    Args:
        actor_class: The hosted resource's ``Akgent`` subclass.

    Returns:
        The declared ``StateType``, or ``None`` when no concrete one exists.
    """
    return _extract_state_type(actor_class)


class StateDelta(SerializableBaseModel):
    """The change a hosted actor reports to its store, as keys rather than a state.

    A delta names what changed and nothing else, which is why a consumer never has to
    rebuild a persisted document by enumerating its fields — the field it forgot to list
    is the field that silently disappears (Golden Rule 12).

    Values are ``JsonValue``: the serialised form of whatever the caller inserted. Neither
    this model nor the store inspects, interprets or transforms one.

    Attributes:
        set: Fields to write, keyed by the path the caller chose. Stored verbatim.
        unset: Field keys to remove.
    """

    set: dict[str, JsonValue] = {}
    unset: list[str] = []


@runtime_checkable
class ResourceStore(Protocol):
    """Where a hosted actor's state is restored from and written back to.

    Core ships this Protocol and nothing else: it has no database dependency and gains
    none. An implementation lives in whichever package owns the persistence.

    ``scope`` is the host's registry key, which is ``config.name`` verbatim. The host does
    no parsing and derives nothing from it, so a store that wants structure in the key must
    put it there itself.

    Both methods take the hosted resource's ``actor_class`` first, for two reasons:

    1. **It namespaces the document.** The host hosts any ``Akgent`` subclass, so two
       resource kinds can meet at one scope string; keyed on the scope alone they would be
       one document, and one kind's delta would corrupt the other's. Keyed on the class as
       well they are two. Deriving the key from the class is the *store's* job and core has
       no opinion about it — ``f"{cls.__module__}.{cls.__qualname__}"`` is the safe
       derivation, bare ``__name__`` collides across packages.
    2. **It is how the store gets a concrete state type.** A stored document is assembled
       from :class:`StateDelta` keys and carries no root type marker, so its class cannot
       come from the document. Pass the class to :func:`resolve_state_type`.

    Note:
        ``runtime_checkable`` makes ``isinstance`` check method *presence* only. It has
        never checked signatures, so an implementation whose parameters drift still passes
        the check; only ``mypy`` catches that.
    """

    def load(self, actor_class: type[Akgent[Any, Any]], scope: str) -> BaseState | None:
        """Restore the state stored under *actor_class* and *scope*.

        Args:
            actor_class: The hosted resource's ``Akgent`` subclass. Namespaces the
                document, and is what :func:`resolve_state_type` turns into the state
                class to rebuild into.
            scope: The host's registry key for the resource.

        Returns:
            The stored state, or ``None`` when nothing is stored for this pair.
        """
        ...

    def apply(self, actor_class: type[Akgent[Any, Any]], scope: str, delta: StateDelta) -> None:
        """Absorb *delta* into the document stored under *actor_class* and *scope*.

        The store writes the delta's values as given; it never inspects them.

        Args:
            actor_class: The hosted resource's ``Akgent`` subclass, namespacing the
                document exactly as it does for :meth:`load`.
            scope: The host's registry key for the resource.
            delta: The fields to set and the field keys to remove.
        """
        ...


@dataclass(frozen=True)
class _HostedEntry:
    """What the host records for one scope: the live actor, and what kind it is.

    Not exported and not a :class:`SerializableBaseModel` — it holds a live
    ``ActorAddress`` and a class object, neither of which serialises (Golden Rule 1b).

    The class is here because :meth:`ResourceHost.notify_delta` is called by a hosted
    actor with a scope and nothing else, so the registry is the host's only route to the
    class the store must be given. The alternative — the hosted actor sending its own
    ``type(self)`` — would let the sender choose the namespace, which is a worse trade
    than the delta a restarted host loses.

    Attributes:
        address: The hosted actor's address.
        actor_class: The class it was created from, passed to the store on every call.
    """

    address: ActorAddress
    actor_class: type[Akgent[Any, Any]]


class ResourceHost(Akgent[BaseConfig, BaseState]):
    """One live actor per name, restored from a store and written back through deltas.

    Created explicitly by whoever wires the process, exactly once, and found by lookup
    afterwards. Nothing constructs a host lazily or caches one in a module global: two
    hosts in one process is the defect this class exists to remove, and a convenience that
    let a second one appear would reintroduce it a level up.

    This is the generic base. Each resource kind — a workspace, a memory, a vector store —
    subclasses it in the package that owns the kind, and exactly one instance of each
    concrete class runs per process. The orchestrator's forward looks that class up
    exactly, never a subclass of it, so two kinds are two hosts and this registry is the
    kind's own silo: a store call stuck on one kind blocks nothing of another, and no pair
    key is needed to tell them apart.
    """

    @override
    def on_start(self) -> None:
        """Initialise the registry and the store handle in the actor's own thread.

        Pykka runs ``on_start`` before the receive loop, so nothing can reach the mailbox
        ahead of these assignments. This mirrors ``Orchestrator``, which initialises its
        mutable state here rather than in ``__init__`` for the same reason.
        """
        self._registry: dict[str, _HostedEntry] = {}
        self._store: ResourceStore | None = None

    def register_store(self, store: ResourceStore) -> None:
        """Attach the store this host restores from and writes back to.

        A store is a client with a live connection, so it cannot sit in a config
        (Golden Rule 1b) and arrives after creation instead. Idempotent by overwrite:
        no validation, no connection check, no reconciliation of what is already hosted.

        Args:
            store: The store to use from now on.
        """
        self._store = store
        logger.info("[%s] store registered: %s", self.config.name, type(store).__name__)

    ##
    ## Store access — the only place a store error is handled
    ##
    def _load(self, actor_class: type[Akgent[Any, Any]], scope: str) -> BaseState | None:
        """Restore the state for *scope*, answering ``None`` on a cold host or a failure.

        The host must not die: it is stateless apart from the registry, and a hosted actor
        outlives it, so a restarted host with an empty registry would create a second actor
        on a live tree. It also cannot lean on ``Akgent._handle_failure``, which with no
        orchestrator sends its ``ErrorMessage`` nowhere. Hence the swallow, here and in
        :meth:`_apply`.

        Args:
            actor_class: The hosted resource's class, passed through to the store.
            scope: The registry key whose state is wanted.

        Returns:
            The stored state, or ``None`` when the host is cold, nothing is stored, or the
            store raised.
        """
        if self._store is None:
            return None
        try:
            return self._store.load(actor_class, scope)
        except Exception:
            logger.error(
                "[%s] store load failed for scope %s", self.config.name, scope, exc_info=True
            )
            return None

    def _apply(self, actor_class: type[Akgent[Any, Any]], scope: str, delta: StateDelta) -> None:
        """Write *delta* back for *scope*, doing nothing on a cold host or a failure.

        Args:
            actor_class: The hosted resource's class, passed through to the store.
            scope: The registry key the delta belongs to.
            delta: The fields to set and the field keys to remove.
        """
        if self._store is None:
            return
        try:
            self._store.apply(actor_class, scope, delta)
        except Exception:
            logger.error(
                "[%s] store apply failed for scope %s", self.config.name, scope, exc_info=True
            )

    ##
    ## Get-or-create
    ##
    def getResourceOrCreate(  # noqa: N802
        self, actor_class: type[Akgent[Any, Any]], config: BaseConfig
    ) -> ActorAddress:
        """Return the live actor registered under ``config.name``, creating it on a miss.

        A registry entry whose actor is no longer alive is a miss, not a hit: the entry is
        replaced rather than duplicated. Liveness here is pykka's stopped flag — whether the
        actor can still receive — and it is not a health probe and must never become one.

        A scope belongs to exactly one actor class, and the caller owns that invariant: on a
        hit the registered actor is returned whatever *actor_class* asks for, unverified and
        unlogged. Two classes sharing one host must therefore be keyed apart by name — the
        host cannot tell them apart, because it never learns what a name means.

        Args:
            actor_class: The ``Akgent`` subclass to instantiate on a miss. Ignored on a hit.
            config: Configuration for the hosted actor. ``config.name`` is the registry key
                and is used verbatim.

        Returns:
            The address of the hosted actor, live in either case.
        """
        scope = config.name
        entry = self._registry.get(scope)
        if entry is not None and entry.address.is_alive():
            return entry.address

        state = self._load(actor_class, scope)
        address = self._start_hosted(actor_class, config)
        if state is not None:
            # Non-blocking on purpose (ADR-012): an actor must never block its own thread
            # on another actor's reply. Ordering is still guaranteed — this and every
            # later message to the hosted actor share one FIFO mailbox, so the state is
            # in place before the caller's first message is handled.
            self.proxy_tell(address, Akgent).init_state(state)
        self._registry[scope] = _HostedEntry(address=address, actor_class=actor_class)
        return address

    def _start_hosted(
        self, actor_class: type[Akgent[Any, Any]], config: BaseConfig
    ) -> ActorAddress:
        """Start a hosted actor as a root actor, owned by nobody.

        Deliberately ``actor_class.start(...)`` and not ``Akgent.createActor``, which would
        append the actor to ``self._children``, set its ``parent`` to this host, force the
        host's ``team_id`` onto it, and thereby drag it into the host's blocking ``stop()``.
        That ownership is precisely what a hosted actor must not have: it outlives the host
        and every team that reaches it.

        Calling ``start()`` directly is legal here and only here — CLAUDE.md's
        actor-internals rule exempts ``akgentic-core``, which owns the actor implementation.

        The host propagates its own ``user_id`` / ``user_email``, which for a
        wiring-created host is ``None``. That is deliberate: a hosted actor takes its
        identity from its resolved ``config``, never from a user carried down the tree.

        Args:
            actor_class: The ``Akgent`` subclass to instantiate.
            config: Configuration for the hosted actor.

        Returns:
            The address of the newly started actor.
        """
        actor = actor_class.start(
            agent_id=None,
            config=config,
            user_id=self._user_id,
            user_email=self._user_email,
            team_id=None,
            parent=None,
            orchestrator=None,
        )
        return ActorAddressImpl(actor)

    ##
    ## Write-back and reclamation
    ##
    def notify_delta(self, scope: str, delta: StateDelta) -> None:
        """Record a hosted actor's state change against its stored document.

        A method rather than a ``Message``: a hosted actor already holds a typed proxy to
        the host, which is how every other actor-to-actor call in the framework is shaped.

        The signature carries only the scope, so the store's ``actor_class`` comes from the
        registry entry. A delta for a scope with no entry is **dropped** and logged: the
        host cannot invent a class, and writing under a guessed one would corrupt another
        kind's document rather than lose one delta.

        A hosted actor that reports a delta from its own ``init_state`` is not this case.
        That delivery is a ``proxy_tell``, so ``getResourceOrCreate`` records the entry
        before the host can dequeue the delta; the two share one FIFO mailbox and the entry
        is always in place first.

        Args:
            scope: The registry key the delta belongs to.
            delta: The fields to set and the field keys to remove.
        """
        entry = self._registry.get(scope)
        if entry is None:
            logger.warning(
                "[%s] delta dropped: no registry entry for scope %s", self.config.name, scope
            )
            return
        self._apply(entry.actor_class, scope, delta)

    def receiveMsg_ResourceStopped(self, message: ResourceStopped) -> None:
        """Drop the registry entry for a hosted actor that has stopped, and nothing else.

        The actor is not stopped here — it announced its own stop — and the store is not
        called: the stored document deliberately survives, and is what the next
        get-or-create for this scope restores from.

        Args:
            message: The announcement, carrying the scope that is going away.
        """
        removed = self._registry.pop(message.scope, None)
        if removed is None:
            logger.info("[%s] no registry entry for scope %s", self.config.name, message.scope)
            return
        logger.info("[%s] registry entry dropped for scope %s", self.config.name, message.scope)
