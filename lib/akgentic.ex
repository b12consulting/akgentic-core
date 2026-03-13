defmodule Akgentic do
  @moduledoc """
  Akgentic Core: An Agent Framework powered by Jido and OTP.

  Akgentic provides an actor-based agent framework for building multi-agent
  systems. It is built on top of Jido's pure functional agent architecture
  and OTP's battle-tested runtime.

  ## Core Concepts

  - **Agents** - Autonomous entities that process signals and manage state
  - **Signals** - Typed messages for agent-to-agent communication
  - **Actions** - Pure functions that transform agent state
  - **Orchestrator** - Telemetry and coordination agent
  - **AgentCard** - Agent profile metadata for capability discovery

  ## Quick Start

      # Define an action
      defmodule MyApp.Actions.Echo do
        use Jido.Action,
          name: "echo",
          description: "Echoes a message",
          schema: [
            content: [type: :string, required: true]
          ]

        def run(params, _context) do
          IO.puts("Echo: \#{params.content}")
          {:ok, %{last_echo: params.content}}
        end
      end

      # Define an agent
      defmodule MyApp.EchoAgent do
        use Akgentic.Agent,
          name: "echo_agent",
          description: "An agent that echoes messages",
          schema: [
            last_echo: [type: :string, default: ""]
          ],
          actions: [MyApp.Actions.Echo],
          signal_routes: [
            {"echo", MyApp.Actions.Echo}
          ]
      end

      # Start and interact with the agent
      {:ok, pid} = Akgentic.start_agent(MyApp.EchoAgent, id: "echo-1")
      {:ok, agent} = Akgentic.signal(pid, "echo", %{content: "Hello!"})
      agent.state.last_echo
      # => "Hello!"

  ## Architecture

  Akgentic maps the following concepts from the original Python akgentic framework
  to Jido/OTP patterns:

  | Python (akgentic)       | Elixir (Akgentic + Jido)              |
  |-------------------------|---------------------------------------|
  | `Akgent`                | `Akgentic.Agent` (uses `Jido.Agent`)  |
  | `Message`               | `Akgentic.Signal` / `Jido.Signal`     |
  | `receiveMsg_<Type>`     | `signal_routes` + `Jido.Action`       |
  | `ActorSystem`           | OTP Supervisor + `Jido.AgentServer`   |
  | `BaseConfig`            | Agent schema (NimbleOptions)          |
  | `BaseState`             | Agent state                           |
  | `Orchestrator`          | `Akgentic.Orchestrator`               |
  | `UserProxy`             | `Akgentic.UserProxy`                  |
  | `ActorAddress`          | PID / Registry lookup                 |
  | `AgentCard`             | `Akgentic.AgentCard`                  |
  | `EventSubscriber`       | `Akgentic.EventSubscriber` behaviour  |
  """

  @version "1.0.0-alpha.1"

  @doc """
  Returns the current version of Akgentic.
  """
  def version, do: @version

  @doc """
  Start an agent under the Akgentic supervisor.

  Uses `Jido.AgentServer` to run the agent as a supervised process.

  ## Options

    * `:id` - Unique identifier for the agent (required)

  ## Examples

      {:ok, pid} = Akgentic.start_agent(MyApp.EchoAgent, id: "echo-1")
  """
  @spec start_agent(module(), keyword()) :: {:ok, pid()} | {:error, term()}
  def start_agent(agent_module, opts \\ []) do
    id = Keyword.fetch!(opts, :id)

    child_spec = %{
      id: id,
      start: {Jido.AgentServer, :start_link, [[agent: agent_module.new(id: id)]]},
      restart: :transient
    }

    case DynamicSupervisor.start_child(Akgentic.AgentSupervisor, child_spec) do
      {:ok, pid} -> {:ok, pid}
      {:error, {:already_started, pid}} -> {:ok, pid}
      error -> error
    end
  end

  @doc """
  Send a signal to a running agent (synchronous).

  Creates a `Jido.Signal` and sends it via `Jido.AgentServer.call/2`.

  ## Examples

      {:ok, agent} = Akgentic.signal(pid, "echo", %{content: "Hello!"})
  """
  @spec signal(pid(), String.t(), map(), keyword()) :: {:ok, term()} | {:error, term()}
  def signal(pid, signal_type, params \\ %{}, opts \\ []) do
    source = Keyword.get(opts, :source, "/akgentic")
    signal = Jido.Signal.new!(signal_type, params, source: source)
    Jido.AgentServer.call(pid, signal)
  end

  @doc """
  Send a fire-and-forget signal to a running agent (asynchronous).

  Creates a `Jido.Signal` and sends it via `Jido.AgentServer.cast/2`.

  ## Examples

      :ok = Akgentic.signal_async(pid, "echo", %{content: "Hello!"})
  """
  @spec signal_async(pid(), String.t(), map(), keyword()) :: :ok
  def signal_async(pid, signal_type, params \\ %{}, opts \\ []) do
    source = Keyword.get(opts, :source, "/akgentic")
    signal = Jido.Signal.new!(signal_type, params, source: source)
    Jido.AgentServer.cast(pid, signal)
  end

  @doc """
  Stop a running agent process.

  ## Examples

      Akgentic.stop_agent(pid)
  """
  @spec stop_agent(pid()) :: :ok
  def stop_agent(pid) do
    GenServer.stop(pid, :normal)
  end
end
