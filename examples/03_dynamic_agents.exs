# Dynamic Agents — Spawning Workers at Runtime
#
# This example demonstrates dynamic agent creation:
# - Spawning multiple worker agents at runtime via `Akgentic.start_agent/2`
# - Distributing tasks to workers
# - Collecting results
#
# Maps from Python's `self.createActor()` pattern to Elixir's
# `Akgentic.start_agent/2` + OTP DynamicSupervisor.
#
# Run with: mix run examples/03_dynamic_agents.exs

# =============================================================================
# STEP 1: Define the work action
# =============================================================================

defmodule Examples.DynamicAgents.Actions.ProcessTask do
  @moduledoc "Processes a task and returns a result."
  use Jido.Action,
    name: "process_task",
    description: "Processes a task with optional delay to simulate work",
    schema: [
      task_id: [type: :string, required: true],
      payload: [type: :string, required: true],
      worker_id: [type: :string, required: false, default: "unknown"]
    ]

  def run(%{task_id: task_id, payload: payload} = params, _context) do
    worker = Map.get(params, :worker_id, "unknown")
    result = String.upcase(payload)
    IO.puts("[Worker #{worker}] Processing task #{task_id}: '#{payload}' → '#{result}'")
    {:ok, %{last_task_id: task_id, last_result: result, tasks_completed: 1}}
  end
end

# =============================================================================
# STEP 2: Define the WorkerAgent
# =============================================================================

defmodule Examples.DynamicAgents.WorkerAgent do
  @moduledoc "A worker agent that processes tasks."
  use Akgentic.Agent,
    name: "worker",
    description: "Processes assigned tasks",
    schema: [
      last_task_id: [type: :string, default: ""],
      last_result: [type: :string, default: ""],
      tasks_completed: [type: :integer, default: 0]
    ],
    actions: [Examples.DynamicAgents.Actions.ProcessTask],
    signal_routes: [
      {"process_task", Examples.DynamicAgents.Actions.ProcessTask}
    ]
end

# =============================================================================
# STEP 3: Pure functional path — spawn workers as data structures
# =============================================================================

IO.puts("\n=== Pure Functional Path ===\n")

alias Examples.DynamicAgents.Actions.ProcessTask
alias Examples.DynamicAgents.WorkerAgent

tasks = [
  %{task_id: "t1", payload: "hello world"},
  %{task_id: "t2", payload: "elixir is great"},
  %{task_id: "t3", payload: "otp rocks"}
]

results =
  tasks
  |> Enum.with_index(1)
  |> Enum.map(fn {task, idx} ->
    worker = WorkerAgent.new(id: "worker-#{idx}")
    params = Map.put(task, :worker_id, "worker-#{idx}")
    {worker, _directives} = WorkerAgent.cmd(worker, {ProcessTask, params})
    {task.task_id, worker.state.last_result}
  end)

IO.puts("\nPure functional results:")

Enum.each(results, fn {task_id, result} ->
  IO.puts("  #{task_id} → #{result}")
end)

# =============================================================================
# STEP 4: OTP path — dynamically spawn supervised worker processes
# =============================================================================

IO.puts("\n=== OTP Path: Dynamic Agent Spawning ===\n")

# Spawn three worker agents dynamically under the OTP supervisor
worker_ids = ["worker-a", "worker-b", "worker-c"]

worker_pids =
  Enum.map(worker_ids, fn id ->
    {:ok, pid} = Akgentic.start_agent(WorkerAgent, id: id)
    IO.puts("Spawned agent '#{id}' at PID #{inspect(pid)}")
    {id, pid}
  end)

IO.puts("\nDistributing tasks to workers...")

# Distribute tasks to workers and collect results
task_payloads = ["hello from otp", "dynamic dispatch", "supervisor magic"]

results =
  worker_pids
  |> Enum.zip(task_payloads)
  |> Enum.map(fn {{worker_id, pid}, payload} ->
    {:ok, agent} =
      Akgentic.signal(pid, "process_task", %{
        task_id: worker_id <> "-task",
        payload: payload,
        worker_id: worker_id
      })

    {worker_id, agent.state.last_result}
  end)

IO.puts("\nOTP path results:")

Enum.each(results, fn {worker_id, result} ->
  IO.puts("  #{worker_id} → #{result}")
end)

IO.puts("\nStopping all workers...")

Enum.each(worker_pids, fn {id, pid} ->
  Akgentic.stop_agent(pid)
  IO.puts("Stopped #{id}")
end)

IO.puts("\n[Dynamic Agents] Done!")
