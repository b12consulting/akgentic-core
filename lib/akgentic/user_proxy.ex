defmodule Akgentic.UserProxy do
  @moduledoc """
  UserProxy agent for human-in-the-loop workflows.

  UserProxy acts as a bridge between human users and the agent system.
  It receives signals from agents requesting human input, presents them
  to humans, and routes human responses back to the requesting agents.

  Maps from Python's `UserProxy(Akgent[BaseConfig, BaseState])` class.

  ## Python → Elixir Mapping

  | Python `UserProxy`                     | Elixir `Akgentic.UserProxy`          |
  |----------------------------------------|--------------------------------------|
  | `process_human_input(content, msg)`    | `process_human_input/3`              |
  | `receiveMsg_UserMessage`               | Signal handler via GenServer         |

  ## Examples

      {:ok, proxy} = Akgentic.UserProxy.start_link(name: "human")

      # Agent sends a question to the proxy
      Akgentic.UserProxy.receive_message(proxy, signal)

      # Human provides input
      Akgentic.UserProxy.process_human_input(proxy, "Continue with option A", reply_to: sender_pid)

      # Get pending messages
      pending = Akgentic.UserProxy.get_pending_messages(proxy)
  """

  use GenServer

  require Logger

  defstruct [
    :name,
    pending_messages: [],
    message_handler: nil
  ]

  @type t :: %__MODULE__{
          name: String.t(),
          pending_messages: [Akgentic.Signal.t()],
          message_handler: (Akgentic.Signal.t() -> :ok) | nil
        }

  # --- Public API ---

  @doc """
  Start the UserProxy process.

  ## Options

    * `:name` - Proxy name (default: "user_proxy")
    * `:server_name` - Optional GenServer name for registration
    * `:message_handler` - Optional callback for incoming messages
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, "user_proxy")
    server_name = Keyword.get(opts, :server_name, nil)
    handler = Keyword.get(opts, :message_handler, nil)

    gen_opts = if server_name, do: [name: server_name], else: []

    state = %__MODULE__{
      name: name,
      message_handler: handler
    }

    GenServer.start_link(__MODULE__, state, gen_opts)
  end

  @doc """
  Receive a message/signal from an agent requesting human input.

  The signal is stored in the pending queue and optionally forwarded
  to the message_handler callback.
  """
  @spec receive_message(GenServer.server(), Akgentic.Signal.t()) :: :ok
  def receive_message(server, signal) do
    GenServer.cast(server, {:receive_message, signal})
  end

  @doc """
  Process human input and route it back to the requesting agent.

  ## Options

    * `:reply_to` - PID of the agent to send the response to
    * `:source` - Signal source (default: "/user_proxy")
  """
  @spec process_human_input(GenServer.server(), String.t(), keyword()) :: :ok
  def process_human_input(server, content, opts \\ []) do
    GenServer.cast(server, {:process_human_input, content, opts})
  end

  @doc """
  Get all pending messages waiting for human input.
  """
  @spec get_pending_messages(GenServer.server()) :: [Akgentic.Signal.t()]
  def get_pending_messages(server) do
    GenServer.call(server, :get_pending_messages)
  end

  @doc """
  Clear all pending messages.
  """
  @spec clear_pending(GenServer.server()) :: :ok
  def clear_pending(server) do
    GenServer.cast(server, :clear_pending)
  end

  # --- GenServer Callbacks ---

  @impl true
  def init(state) do
    {:ok, state}
  end

  @impl true
  def handle_cast({:receive_message, signal}, state) do
    Logger.info(
      "UserProxy received message from #{signal.source}: " <>
        "#{inspect(get_in(signal.data, [:content]) || signal.data)}"
    )

    # Call handler if configured
    if state.message_handler do
      try do
        state.message_handler.(signal)
      rescue
        e -> Logger.error("UserProxy message handler failed: #{inspect(e)}")
      end
    end

    {:noreply, %{state | pending_messages: state.pending_messages ++ [signal]}}
  end

  @impl true
  def handle_cast({:process_human_input, content, opts}, state) do
    reply_to = Keyword.get(opts, :reply_to, nil)
    source = Keyword.get(opts, :source, "/user_proxy/#{state.name}")

    Logger.info("Received human input: #{content}, at destination of: #{inspect(reply_to)}")

    if reply_to && is_pid(reply_to) && Process.alive?(reply_to) do
      response = Akgentic.Messages.result_message(content, source: source)

      send(reply_to, {:signal, response})
    end

    {:noreply, state}
  end

  @impl true
  def handle_cast(:clear_pending, state) do
    {:noreply, %{state | pending_messages: []}}
  end

  @impl true
  def handle_call(:get_pending_messages, _from, state) do
    {:reply, state.pending_messages, state}
  end
end
