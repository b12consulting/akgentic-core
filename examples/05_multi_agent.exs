# Multi-Agent Workflow
#
# This example demonstrates a multi-agent pipeline:
#   ResearchAgent → WriterAgent → UserProxy (human review)
#
# It also shows:
# - Orchestrator telemetry tracking
# - EventSubscriber for monitoring workflow events
# - UserProxy for human-in-the-loop interaction
#
# Maps from Python's ResearchAgent→WriterAgent→UserProxy workflow
# with Orchestrator telemetry and EventSubscriber.
#
# Run with: mix run examples/05_multi_agent.exs

alias Akgentic.Messages
alias Akgentic.Messages.Orchestrator, as: OrchestratorMessages
alias Akgentic.Orchestrator
alias Akgentic.UserProxy

# =============================================================================
# STEP 1: Define agent actions
# =============================================================================

defmodule Examples.MultiAgent.Actions.Research do
  @moduledoc "Researches a topic and produces findings."
  use Jido.Action,
    name: "research",
    description: "Research a topic and produce findings",
    schema: [
      topic: [type: :string, required: true]
    ]

  def run(%{topic: topic}, _context) do
    IO.puts("[ResearchAgent] Researching topic: '#{topic}'")
    findings = "Key findings on '#{topic}': " <> "OTP provides fault-tolerance via supervision trees."
    {:ok, %{topic: topic, findings: findings}}
  end
end

defmodule Examples.MultiAgent.Actions.Write do
  @moduledoc "Writes an article based on research findings."
  use Jido.Action,
    name: "write",
    description: "Write an article from research findings",
    schema: [
      findings: [type: :string, required: true]
    ]

  def run(%{findings: findings}, _context) do
    IO.puts("[WriterAgent] Writing article from findings...")
    article = "## Article\n\n#{findings}\n\nConclusion: Elixir's OTP model enables scalable systems."
    {:ok, %{article: article}}
  end
end

# =============================================================================
# STEP 2: Define agents
# =============================================================================

defmodule Examples.MultiAgent.ResearchAgent do
  @moduledoc "An agent that researches topics."
  use Akgentic.Agent,
    name: "researcher",
    description: "Researches topics and gathers information",
    schema: [
      topic: [type: :string, default: ""],
      findings: [type: :string, default: ""]
    ],
    actions: [Examples.MultiAgent.Actions.Research],
    signal_routes: [{"research", Examples.MultiAgent.Actions.Research}]
end

defmodule Examples.MultiAgent.WriterAgent do
  @moduledoc "An agent that writes articles from research."
  use Akgentic.Agent,
    name: "writer",
    description: "Writes articles from research findings",
    schema: [
      article: [type: :string, default: ""]
    ],
    actions: [Examples.MultiAgent.Actions.Write],
    signal_routes: [{"write", Examples.MultiAgent.Actions.Write}]
end

# =============================================================================
# STEP 3: Define an EventSubscriber for workflow monitoring
# =============================================================================

defmodule Examples.MultiAgent.WorkflowSubscriber do
  @moduledoc "Monitors workflow events and prints them."
  @behaviour Akgentic.EventSubscriber

  @impl true
  def on_stop do
    IO.puts("[WorkflowSubscriber] Orchestrator stopped — workflow complete")
  end

  @impl true
  def on_message(signal) do
    IO.puts("[WorkflowSubscriber] Event: #{signal.type} from #{signal.source}")
  end
end

# =============================================================================
# STEP 4: Run the multi-agent pipeline
# =============================================================================

IO.puts("\n=== Multi-Agent Pipeline ===\n")

# Start the orchestrator and subscribe the event subscriber
{:ok, orch} = Orchestrator.start_link(name: "multi-agent-orch", timeout_delay: 3600)
Orchestrator.subscribe(orch, Examples.MultiAgent.WorkflowSubscriber)

# Start agents under the supervisor
{:ok, research_pid} = Akgentic.start_agent(Examples.MultiAgent.ResearchAgent, id: "researcher-1")
{:ok, writer_pid} = Akgentic.start_agent(Examples.MultiAgent.WriterAgent, id: "writer-1")
{:ok, proxy} = UserProxy.start_link(name: "human-reviewer")

# Register agent lifecycles with orchestrator
Orchestrator.record_signal(
  orch,
  OrchestratorMessages.agent_started("researcher-1", %{name: "researcher", role: "Researcher"})
)

Orchestrator.record_signal(
  orch,
  OrchestratorMessages.agent_started("writer-1", %{name: "writer", role: "Writer"})
)

Process.sleep(50)

# ---- Step 1: Research ----
topic = "Elixir OTP and fault-tolerant systems"

Orchestrator.record_signal(
  orch,
  OrchestratorMessages.message_received("researcher-1", "msg-research-1")
)

{:ok, research_result} = Akgentic.signal(research_pid, "research", %{topic: topic})
IO.puts("Research complete. Findings: #{research_result.state.findings}")

Orchestrator.record_signal(
  orch,
  OrchestratorMessages.message_processed("researcher-1", "msg-research-1")
)

# ---- Step 2: Write ----
Orchestrator.record_signal(
  orch,
  OrchestratorMessages.message_received("writer-1", "msg-write-1")
)

{:ok, write_result} = Akgentic.signal(writer_pid, "write", %{findings: research_result.state.findings})
IO.puts("Writing complete. Article preview: #{String.slice(write_result.state.article, 0, 80)}...")

Orchestrator.record_signal(
  orch,
  OrchestratorMessages.message_processed("writer-1", "msg-write-1")
)

# ---- Step 3: Human review via UserProxy ----
IO.puts("\n[UserProxy] Sending article for human review...")
article_signal = Messages.result_message(write_result.state.article, source: "/agent/writer-1")
UserProxy.receive_message(proxy, article_signal)

# Simulate human approving the article (in production, a human would call this)
spawn(fn ->
  Process.sleep(300)
  IO.puts("[Human] Reviewing article and providing feedback...")
  UserProxy.process_human_input(proxy, "Approved — excellent article on OTP!")
end)

Process.sleep(600)

pending = UserProxy.get_pending_messages(proxy)
IO.puts("Messages pending human review: #{length(pending)}")

# ---- Orchestrator team and telemetry ----
Process.sleep(100)
team = Orchestrator.get_team(orch)
IO.puts("\nActive team members: #{Enum.map(team, & &1.name) |> Enum.join(", ")}")

messages = Orchestrator.get_messages(orch)
IO.puts("Total orchestrator events: #{length(messages)}")

# Cleanup
Akgentic.stop_agent(research_pid)
Akgentic.stop_agent(writer_pid)
GenServer.stop(proxy)
Orchestrator.stop(orch)

IO.puts("\n[Multi-Agent] Done!")
