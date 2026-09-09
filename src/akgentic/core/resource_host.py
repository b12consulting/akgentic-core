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
from typing import TYPE_CHECKING, Any, Protocol, override, runtime_checkable

from pydantic import JsonValue

from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.utils.serializer import SerializableBaseModel

if TYPE_CHECKING:
    from akgentic.core.actor_address import ActorAddress
    from akgentic.core.messages.message import ResourceStopped

logger = logging.getLogger(__name__)


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

    Note:
        ``runtime_checkable`` makes ``isinstance`` check method *presence* only. It has
        never checked signatures, so an implementation whose parameters drift still passes
        the check; only ``mypy`` catches that.
    """

    def load(self, scope: str) -> BaseState | None:
        """Restore the state stored under *scope*.

        Args:
            scope: The host's registry key for the resource.

        Returns:
            The stored state, or ``None`` when nothing is stored for this scope.
        """
        ...

    def apply(self, scope: str, delta: StateDelta) -> None:
        """Absorb *delta* into the document stored under *scope*.

        The store writes the delta's values as given; it never inspects them.

        Args:
            scope: The host's registry key for the resource.
            delta: The fields to set and the field keys to remove.
        """
        ...


class ResourceHost(Akgent[BaseConfig, BaseState]):
    """One live actor per name, restored from a store and written back through deltas.

    Created explicitly by whoever wires the process, exactly once, and found by lookup
    afterwards. Nothing constructs a host lazily or caches one in a module global: two
    hosts in one process is the defect this class exists to remove, and a convenience that
    let a second one appear would reintroduce it a level up.
    """

    @override
    def on_start(self) -> None:
        """Initialise the registry and the store handle in the actor's own thread.

        Pykka runs ``on_start`` before the receive loop, so nothing can reach the mailbox
        ahead of these assignments. This mirrors ``Orchestrator``, which initialises its
        mutable state here rather than in ``__init__`` for the same reason.
        """
        self._registry: dict[str, ActorAddress] = {}
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
    def _load(self, scope: str) -> BaseState | None:
        """Restore the state for *scope*, answering ``None`` on a cold host or a failure.

        The host must not die: it is stateless apart from the registry, and a hosted actor
        outlives it, so a restarted host with an empty registry would create a second actor
        on a live tree. It also cannot lean on ``Akgent._handle_failure``, which with no
        orchestrator sends its ``ErrorMessage`` nowhere. Hence the swallow, here and in
        :meth:`_apply`.

        Args:
            scope: The registry key whose state is wanted.

        Returns:
            The stored state, or ``None`` when the host is cold, nothing is stored, or the
            store raised.
        """
        if self._store is None:
            return None
        try:
            return self._store.load(scope)
        except Exception:
            logger.error(
                "[%s] store load failed for scope %s", self.config.name, scope, exc_info=True
            )
            return None

    def _apply(self, scope: str, delta: StateDelta) -> None:
        """Write *delta* back for *scope*, doing nothing on a cold host or a failure.

        Args:
            scope: The registry key the delta belongs to.
            delta: The fields to set and the field keys to remove.
        """
        if self._store is None:
            return
        try:
            self._store.apply(scope, delta)
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
        if entry is not None and entry.is_alive():
            return entry

        state = self._load(scope)
        address = self._start_hosted(actor_class, config)
        if state is not None:
            # Non-blocking on purpose (ADR-012): an actor must never block its own thread
            # on another actor's reply. Ordering is still guaranteed — this and every
            # later message to the hosted actor share one FIFO mailbox, so the state is
            # in place before the caller's first message is handled.
            self.proxy_tell(address, Akgent).init_state(state)
        self._registry[scope] = address
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

        Args:
            scope: The registry key the delta belongs to.
            delta: The fields to set and the field keys to remove.
        """
        self._apply(scope, delta)

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
