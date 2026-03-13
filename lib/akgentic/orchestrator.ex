defmodule Akgentic.Orchestrator do
  @moduledoc """
  Orchestrator agent for workflow coordination and telemetry tracking.

  The Orchestrator manages workflow coordination and telemetry tracking.
  It maintains in-memory storage of:
    - Message history (all telemetry events)
    - Per-agent state snapshots
    - Agent profile catalog
    - Team roster (computed from message history)

  Maps from Python's `Orchestrator(Akgent[BaseConfig, BaseState])` class.

  ## Python → Elixir Mapping

  | Python `Orchestrator`                  | Elixir `Akgentic.Orchestrator`         |
  |----------------------------------------|----------------------------------------|
  | `Orchestrator.messages`                | GenServer state `:messages`            |
  | `Orchestrator.state_dict`              | GenServer state `:agent_states`        |
  | `Orchestrator.agent_cards`             | GenServer state `:agent_cards`         |
  | `Orchestrator.subscribers`             | GenServer state `:subscribers`         |
  | `Orchestrator._timer`                  | Linked `Akgentic.Timer` process        |
  | `receiveMsg_StartMessage`              | `handle_signal/2` with type matching   |
  | `receiveMsg_ReceivedMessage`           | Timer task_started on message received |
  | `receiveMsg_ProcessedMessage`          | Timer task_completed on processed      |

  ## Examples

      {:ok, orch} = Akgentic.Orchestrator.start_link(name: "orchestrator")
      Akgentic.Orchestrator.record_signal(orch, signal)
      messages = Akgentic.Orchestrator.get_messages(orch)
      team = Akgentic.Orchestrator.get_team(orch)
  """

  use GenServer

  require Logger

  alias Akgentic.AgentCard
  alias Akgentic.Messages.Orchestrator, as: OrchestratorMessages
  alias Akgentic.Timer

  defstruct [
    :name,
    :timer_pid,
    messages: [],
    agent_states: %{},
    agent_cards: %{},
    subscribers: [],
    stopping: false,
    team_cache: nil
  ]

  @type t :: %__MODULE__{
          name: String.t(),
          timer_pid: pid() | nil,
          messages: [Akgentic.Signal.t()],
          agent_states: %{String.t() => map()},
          agent_cards: %{String.t() => AgentCard.t()},
          subscribers: [module()],
          stopping: boolean(),
          team_cache: [map()] | nil
        }

  # --- Public API ---

  @doc """
  Start the orchestrator process.

  ## Options

    * `:name` - Orchestrator name (default: "orchestrator")
    * `:timeout_delay` - Inactivity timeout in seconds (default: from config or 3600)
    * `:server_name` - Optional GenServer name for registration
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, "orchestrator")
    server_name = Keyword.get(opts, :server_name, nil)

    gen_opts = if server_name, do: [name: server_name], else: []

    GenServer.start_link(__MODULE__, Map.put(Map.new(opts), :name, name), gen_opts)
  end

  @doc """
  Record a telemetry signal in the orchestrator.

  Dispatches the signal to the appropriate handler based on signal type.
  """
  @spec record_signal(GenServer.server(), Akgentic.Signal.t()) :: :ok
  def record_signal(server, signal) do
    GenServer.cast(server, {:record_signal, signal})
  end

  @doc """
  Subscribe to orchestrator events.
  """
  @spec subscribe(GenServer.server(), module()) :: :ok
  def subscribe(server, subscriber) do
    GenServer.cast(server, {:subscribe, subscriber})
  end

  @doc """
  Get all recorded messages.
  """
  @spec get_messages(GenServer.server()) :: [Akgentic.Signal.t()]
  def get_messages(server) do
    GenServer.call(server, :get_messages)
  end

  @doc """
  Get active team members (agents that have started but not stopped).
  """
  @spec get_team(GenServer.server()) :: [map()]
  def get_team(server) do
    GenServer.call(server, :get_team)
  end

  @doc """
  Get a team member by name.
  """
  @spec get_team_member(GenServer.server(), String.t()) :: map() | nil
  def get_team_member(server, name) do
    GenServer.call(server, {:get_team_member, name})
  end

  @doc """
  Get all agent states tracked by orchestrator.
  """
  @spec get_states(GenServer.server()) :: %{String.t() => map()}
  def get_states(server) do
    GenServer.call(server, :get_states)
  end

  @doc """
  Get the timer process PID.
  """
  @spec get_timer(GenServer.server()) :: pid() | nil
  def get_timer(server) do
    GenServer.call(server, :get_timer)
  end

  @doc """
  Register an agent profile in the team catalog.
  """
  @spec register_agent_profile(GenServer.server(), AgentCard.t()) :: :ok
  def register_agent_profile(server, card) do
    GenServer.cast(server, {:register_agent_profile, card})
  end

  @doc """
  Register multiple agent profiles.
  """
  @spec register_agent_profiles(GenServer.server(), [AgentCard.t()]) :: :ok
  def register_agent_profiles(server, cards) do
    Enum.each(cards, &register_agent_profile(server, &1))
  end

  @doc """
  Get all available agent profiles in the team catalog.
  """
  @spec get_agent_catalog(GenServer.server()) :: [AgentCard.t()]
  def get_agent_catalog(server) do
    GenServer.call(server, :get_agent_catalog)
  end

  @doc """
  Get a specific agent profile by role.
  """
  @spec get_agent_profile(GenServer.server(), String.t()) :: AgentCard.t() | nil
  def get_agent_profile(server, role) do
    GenServer.call(server, {:get_agent_profile, role})
  end

  @doc """
  Find all agent profiles that have a specific skill.
  """
  @spec get_profiles_by_skill(GenServer.server(), String.t()) :: [AgentCard.t()]
  def get_profiles_by_skill(server, skill) do
    GenServer.call(server, {:get_profiles_by_skill, skill})
  end

  @doc """
  Get list of all roles available in the catalog.
  """
  @spec get_available_roles(GenServer.server()) :: [String.t()]
  def get_available_roles(server) do
    GenServer.call(server, :get_available_roles)
  end

  @doc """
  Get unique set of all skills across all profiles.
  """
  @spec get_available_skills(GenServer.server()) :: [String.t()]
  def get_available_skills(server) do
    GenServer.call(server, :get_available_skills)
  end

  @doc """
  Stop the orchestrator gracefully.
  """
  @spec stop(GenServer.server()) :: :ok
  def stop(server) do
    GenServer.stop(server, :normal)
  end

  # --- GenServer Callbacks ---

  @impl true
  def init(opts) do
    name = Map.get(opts, :name, "orchestrator")

    default_delay = Application.get_env(:akgentic, :orchestrator_timeout_delay, 3_600)
    timeout_delay = Map.get(opts, :timeout_delay, default_delay)

    {:ok, timer_pid} =
      Timer.start_link(
        delay: timeout_delay,
        on_timeout: fn ->
          Logger.info("Orchestrator timeout after #{timeout_delay}s inactivity (name=#{name})")
          # Send stop to self
          send(self(), :timeout_stop)
        end
      )

    Timer.start_countdown(timer_pid)

    state = %__MODULE__{
      name: name,
      timer_pid: timer_pid
    }

    # Record own startup
    startup_signal =
      OrchestratorMessages.agent_started("orchestrator", %{name: name, role: "Orchestrator"})

    {:ok, handle_signal_internal(state, startup_signal)}
  end

  @impl true
  def handle_cast({:record_signal, signal}, state) do
    {:noreply, handle_signal_internal(state, signal)}
  end

  @impl true
  def handle_cast({:subscribe, subscriber}, state) do
    {:noreply, %{state | subscribers: [subscriber | state.subscribers]}}
  end

  @impl true
  def handle_cast({:register_agent_profile, card}, state) do
    Logger.info("[Orchestrator] Registered agent profile: #{card.role}")
    {:noreply, %{state | agent_cards: Map.put(state.agent_cards, card.role, card)}}
  end

  @impl true
  def handle_call(:get_messages, _from, state) do
    {:reply, Enum.reverse(state.messages), state}
  end

  @impl true
  def handle_call(:get_team, _from, state) do
    {team, state} = compute_team(state)
    {:reply, team, state}
  end

  @impl true
  def handle_call({:get_team_member, name}, _from, state) do
    {team, state} = compute_team(state)
    member = Enum.find(team, fn m -> m.name == name end)
    {:reply, member, state}
  end

  @impl true
  def handle_call(:get_states, _from, state) do
    {:reply, state.agent_states, state}
  end

  @impl true
  def handle_call(:get_timer, _from, state) do
    {:reply, state.timer_pid, state}
  end

  @impl true
  def handle_call(:get_agent_catalog, _from, state) do
    {:reply, Map.values(state.agent_cards), state}
  end

  @impl true
  def handle_call({:get_agent_profile, role}, _from, state) do
    {:reply, Map.get(state.agent_cards, role), state}
  end

  @impl true
  def handle_call({:get_profiles_by_skill, skill}, _from, state) do
    profiles =
      state.agent_cards
      |> Map.values()
      |> Enum.filter(&AgentCard.has_skill?(&1, skill))

    {:reply, profiles, state}
  end

  @impl true
  def handle_call(:get_available_roles, _from, state) do
    {:reply, Map.keys(state.agent_cards), state}
  end

  @impl true
  def handle_call(:get_available_skills, _from, state) do
    skills =
      state.agent_cards
      |> Map.values()
      |> Enum.flat_map(& &1.skills)
      |> Enum.uniq()
      |> Enum.sort()

    {:reply, skills, state}
  end

  @impl true
  def handle_info(:timeout_stop, state) do
    notify_subscribers(state.subscribers, :on_stop, nil)
    {:stop, :normal, state}
  end

  @impl true
  def terminate(_reason, state) do
    if state.timer_pid && Process.alive?(state.timer_pid) do
      Timer.cancel(state.timer_pid)
      GenServer.stop(state.timer_pid, :normal)
    end

    notify_subscribers(state.subscribers, :on_stop, nil)
    Logger.info(">>> [#{state.name}] Stopped!")
    :ok
  end

  # --- Private Helpers ---

  defp handle_signal_internal(state, signal) do
    type = signal.type

    cond do
      type == OrchestratorMessages.type_agent_started() ->
        state
        |> append_message(signal)
        |> clear_team_cache()
        |> notify_and_return(signal)

      type == OrchestratorMessages.type_agent_stopped() ->
        if state.stopping do
          state
        else
          state
          |> append_message(signal)
          |> clear_team_cache()
          |> notify_and_return(signal)
        end

      type == OrchestratorMessages.type_message_sent() ->
        state
        |> append_message(signal)
        |> notify_and_return(signal)

      type == OrchestratorMessages.type_message_received() ->
        Timer.task_started(state.timer_pid)

        state
        |> append_message(signal)
        |> notify_and_return(signal)

      type == OrchestratorMessages.type_message_processed() ->
        Timer.task_completed(state.timer_pid)

        state
        |> append_message(signal)
        |> notify_and_return(signal)

      type == OrchestratorMessages.type_agent_error() ->
        state
        |> append_message(signal)
        |> notify_and_return(signal)

      type == OrchestratorMessages.type_state_changed() ->
        agent_id = get_in(signal.data, [:agent_id]) || get_in(signal.data, ["agent_id"])

        state =
          if agent_id do
            new_agent_state =
              get_in(signal.data, [:state]) || get_in(signal.data, ["state"]) || %{}

            %{state | agent_states: Map.put(state.agent_states, to_string(agent_id), new_agent_state)}
          else
            state
          end

        notify_and_return(state, signal)

      type == OrchestratorMessages.type_agent_event() ->
        notify_and_return(state, signal)

      true ->
        # Unknown signal type - just record it
        append_message(state, signal)
    end
  end

  defp append_message(state, signal) do
    %{state | messages: [signal | state.messages]}
  end

  defp clear_team_cache(state) do
    %{state | team_cache: nil}
  end

  defp notify_and_return(state, signal) do
    notify_subscribers(state.subscribers, :on_message, signal)
    state
  end

  defp notify_subscribers(subscribers, event_method, signal) do
    alias Akgentic.EventSubscriber

    Enum.each(subscribers, fn subscriber ->
      try do
        case event_method do
          :on_stop -> EventSubscriber.invoke_on_stop(subscriber)
          :on_message -> EventSubscriber.invoke_on_message(subscriber, signal)
        end
      rescue
        e ->
          Logger.error("Subscriber #{inspect(subscriber)} failed #{event_method}: #{inspect(e)}")
      end
    end)
  end

  defp compute_team(state) do
    case state.team_cache do
      nil ->
        messages = Enum.reverse(state.messages)

        started =
          messages
          |> Enum.filter(fn s -> s.type == OrchestratorMessages.type_agent_started() end)
          |> Enum.reject(fn s ->
            config = get_in(s.data, [:config]) || get_in(s.data, ["config"]) || %{}
            role = Map.get(config, :role) || Map.get(config, "role")
            role == "Orchestrator"
          end)
          |> Enum.map(fn s ->
            agent_id = get_in(s.data, [:agent_id]) || get_in(s.data, ["agent_id"])
            config = get_in(s.data, [:config]) || get_in(s.data, ["config"]) || %{}
            name = Map.get(config, :name) || Map.get(config, "name") || agent_id

            %{
              agent_id: to_string(agent_id),
              name: name,
              role: Map.get(config, :role) || Map.get(config, "role"),
              source: s.source
            }
          end)
          |> Enum.reduce(%{}, fn member, acc ->
            Map.put(acc, member.agent_id, member)
          end)

        stopped_ids =
          messages
          |> Enum.filter(fn s -> s.type == OrchestratorMessages.type_agent_stopped() end)
          |> Enum.map(fn s ->
            agent_id = get_in(s.data, [:agent_id]) || get_in(s.data, ["agent_id"])
            to_string(agent_id)
          end)
          |> MapSet.new()

        team =
          started
          |> Enum.reject(fn {aid, _} -> MapSet.member?(stopped_ids, aid) end)
          |> Enum.map(fn {_, member} -> member end)

        {team, %{state | team_cache: team}}

      cached ->
        {cached, state}
    end
  end
end
