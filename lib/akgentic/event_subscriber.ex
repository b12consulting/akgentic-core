defmodule Akgentic.EventSubscriber do
  @moduledoc """
  Behaviour for subscribing to orchestrator events.

  Implementations can provide custom handling for workflow events such as
  Redis publishing, WebSocket streaming, or database persistence.

  Maps from Python's `EventSubscriber` Protocol.

  A subscriber can be either:
  1. A module implementing the `Akgentic.EventSubscriber` behaviour
  2. A map with `:on_stop` and `:on_message` function keys

  ## Module-based subscriber

      defmodule MySubscriber do
        @behaviour Akgentic.EventSubscriber

        @impl true
        def on_stop do
          IO.puts("Orchestrator stopped")
        end

        @impl true
        def on_message(signal) do
          IO.inspect(signal, label: "Event")
        end
      end

  ## Map-based subscriber

      subscriber = %{
        on_stop: fn -> IO.puts("Stopped") end,
        on_message: fn signal -> IO.inspect(signal) end
      }
  """

  @doc "Called when an orchestrator stops."
  @callback on_stop() :: :ok

  @doc """
  Called when an agent lifecycle message is received.

  Signal types include:
    - `akgentic.agent.started`
    - `akgentic.agent.stopped`
    - `akgentic.message.sent`
    - `akgentic.message.received`
    - `akgentic.message.processed`
    - `akgentic.agent.error`
    - `akgentic.agent.state_changed`
    - `akgentic.agent.event`
  """
  @callback on_message(signal :: map()) :: :ok

  @doc """
  Invoke the on_stop callback on a subscriber.

  Works with both module-based and map-based subscribers.
  """
  @spec invoke_on_stop(module() | map()) :: :ok
  def invoke_on_stop(subscriber) when is_atom(subscriber), do: subscriber.on_stop()
  def invoke_on_stop(%{on_stop: fun}) when is_function(fun, 0), do: fun.()
  def invoke_on_stop(_), do: :ok

  @doc """
  Invoke the on_message callback on a subscriber.

  Works with both module-based and map-based subscribers.
  """
  @spec invoke_on_message(module() | map(), map()) :: :ok
  def invoke_on_message(subscriber, signal) when is_atom(subscriber),
    do: subscriber.on_message(signal)

  def invoke_on_message(%{on_message: fun}, signal) when is_function(fun, 1),
    do: fun.(signal)

  def invoke_on_message(_, _), do: :ok
end
