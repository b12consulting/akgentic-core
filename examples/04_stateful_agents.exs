# Stateful Agents — Typed State, Mutations, and Orchestrator Tracking
#
# This example demonstrates:
# - Defining typed agent state with Jido schema (min/max/default constraints)
# - Actions that mutate state with clamping logic
# - Orchestrator tracking state change telemetry
#
# Maps from Python's CounterConfig/CounterState, observer pattern, and
# state mutation with notification to Jido agent schema + Orchestrator signals.
#
# Run with: mix run examples/04_stateful_agents.exs

alias Akgentic.Messages.Orchestrator, as: OrchestratorMessages
alias Akgentic.Orchestrator

# =============================================================================
# STEP 1: Define stateful actions
# =============================================================================

defmodule Examples.StatefulAgents.Actions.Increment do
  @moduledoc "Increments the counter, clamped to max_value."
  use Jido.Action,
    name: "increment",
    description: "Increments the counter by a given amount",
    schema: [
      amount: [type: :integer, default: 1]
    ]

  def run(%{amount: amount}, context) do
    current = get_in(context, [:agent, :state, :count]) || 0
    max_val = get_in(context, [:agent, :state, :max_value]) || 100
    new_count = min(current + amount, max_val)
    IO.puts("[CounterAgent] increment(#{amount}): #{current} → #{new_count}")
    {:ok, %{count: new_count}}
  end
end

defmodule Examples.StatefulAgents.Actions.Decrement do
  @moduledoc "Decrements the counter, clamped to min_value."
  use Jido.Action,
    name: "decrement",
    description: "Decrements the counter by a given amount",
    schema: [
      amount: [type: :integer, default: 1]
    ]

  def run(%{amount: amount}, context) do
    current = get_in(context, [:agent, :state, :count]) || 0
    min_val = get_in(context, [:agent, :state, :min_value]) || 0
    new_count = max(current - amount, min_val)
    IO.puts("[CounterAgent] decrement(#{amount}): #{current} → #{new_count}")
    {:ok, %{count: new_count}}
  end
end

defmodule Examples.StatefulAgents.Actions.Reset do
  @moduledoc "Resets the counter to zero."
  use Jido.Action,
    name: "reset",
    description: "Resets the counter to zero",
    schema: []

  def run(_params, context) do
    current = get_in(context, [:agent, :state, :count]) || 0
    IO.puts("[CounterAgent] reset: #{current} → 0")
    {:ok, %{count: 0}}
  end
end

# =============================================================================
# STEP 2: Define the CounterAgent with typed schema
# =============================================================================

defmodule Examples.StatefulAgents.CounterAgent do
  @moduledoc "A stateful counter agent with typed schema and clamping logic."
  use Akgentic.Agent,
    name: "counter",
    description: "A stateful counter with min/max clamping",
    schema: [
      count: [type: :integer, default: 0],
      min_value: [type: :integer, default: 0],
      max_value: [type: :integer, default: 100]
    ],
    actions: [
      Examples.StatefulAgents.Actions.Increment,
      Examples.StatefulAgents.Actions.Decrement,
      Examples.StatefulAgents.Actions.Reset
    ],
    signal_routes: [
      {"increment", Examples.StatefulAgents.Actions.Increment},
      {"decrement", Examples.StatefulAgents.Actions.Decrement},
      {"reset", Examples.StatefulAgents.Actions.Reset}
    ]
end

# =============================================================================
# STEP 3: Pure functional path — state mutations via cmd/2
# =============================================================================

IO.puts("\n=== Pure Functional Path ===\n")

alias Examples.StatefulAgents.Actions.Increment
alias Examples.StatefulAgents.Actions.Decrement
alias Examples.StatefulAgents.Actions.Reset
alias Examples.StatefulAgents.CounterAgent

agent = CounterAgent.new()
IO.puts("Initial count: #{agent.state.count}")
IO.puts("Schema: min=#{agent.state.min_value}, max=#{agent.state.max_value}")

{agent, _} = CounterAgent.cmd(agent, {Increment, %{amount: 10}})
IO.puts("After +10: #{agent.state.count}")

{agent, _} = CounterAgent.cmd(agent, {Increment, %{amount: 50}})
IO.puts("After +50: #{agent.state.count}")

{agent, _} = CounterAgent.cmd(agent, {Decrement, %{amount: 25}})
IO.puts("After -25: #{agent.state.count}")

{agent, _} = CounterAgent.cmd(agent, {Reset, %{}})
IO.puts("After reset: #{agent.state.count}")

# Clamping test — incrementing past max_value
{agent, _} = CounterAgent.cmd(agent, {Increment, %{amount: 200}})
IO.puts("After +200 (clamped at #{agent.state.max_value}): #{agent.state.count}")

# =============================================================================
# STEP 4: OTP path — signals with Orchestrator state-change tracking
# =============================================================================

IO.puts("\n=== OTP Path with Orchestrator Tracking ===\n")

{:ok, orch} = Orchestrator.start_link(name: "stateful-orch", timeout_delay: 3600)
{:ok, pid} = Akgentic.start_agent(CounterAgent, id: "counter-tracked")

# Register agent start with orchestrator
Orchestrator.record_signal(
  orch,
  OrchestratorMessages.agent_started("counter-tracked", %{name: "counter", role: "Counter"})
)

# Perform increments and track state changes
Enum.each([10, 20, 30], fn amount ->
  {:ok, updated} = Akgentic.signal(pid, "increment", %{amount: amount})
  IO.puts("After signal increment(#{amount}): count = #{updated.state.count}")

  # Record state change to orchestrator
  Orchestrator.record_signal(
    orch,
    OrchestratorMessages.state_changed("counter-tracked", %{count: updated.state.count})
  )
end)

# Inspect orchestrator state tracking
Process.sleep(100)
states = Orchestrator.get_states(orch)
IO.puts("\nOrchestrator tracked state for 'counter-tracked': #{inspect(states["counter-tracked"])}")

messages = Orchestrator.get_messages(orch)
state_changes = Enum.filter(messages, fn m -> m.type == "akgentic.agent.state_changed" end)
IO.puts("Total state_changed events recorded: #{length(state_changes)}")

Akgentic.stop_agent(pid)
Orchestrator.stop(orch)

IO.puts("\n[Stateful Agents] Done!")
