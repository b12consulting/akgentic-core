defmodule Akgentic.OrchestratorTest do
  use ExUnit.Case, async: true

  alias Akgentic.AgentCard
  alias Akgentic.Messages.Orchestrator, as: OrchestratorMessages
  alias Akgentic.Orchestrator
  alias Akgentic.Timer

  setup do
    {:ok, orch} = Orchestrator.start_link(name: "test-orchestrator", timeout_delay: 3600)
    %{orch: orch}
  end

  describe "start_link/1" do
    test "starts the orchestrator process", %{orch: orch} do
      assert Process.alive?(orch)
    end

    test "records own startup message", %{orch: orch} do
      messages = Orchestrator.get_messages(orch)
      assert length(messages) >= 1

      startup = hd(messages)
      assert startup.type == OrchestratorMessages.type_agent_started()
    end
  end

  describe "record_signal/2" do
    test "records agent started signals", %{orch: orch} do
      signal = OrchestratorMessages.agent_started("worker-1", %{name: "worker", role: "Worker"})
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      messages = Orchestrator.get_messages(orch)
      assert length(messages) >= 2
    end

    test "records agent stopped signals", %{orch: orch} do
      signal = OrchestratorMessages.agent_stopped("worker-1")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      messages = Orchestrator.get_messages(orch)
      assert Enum.any?(messages, fn s -> s.type == OrchestratorMessages.type_agent_stopped() end)
    end

    test "records error signals", %{orch: orch} do
      signal = OrchestratorMessages.agent_error("worker-1", "RuntimeError", "boom")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      messages = Orchestrator.get_messages(orch)
      assert Enum.any?(messages, fn s -> s.type == OrchestratorMessages.type_agent_error() end)
    end

    test "tracks state changes", %{orch: orch} do
      signal = OrchestratorMessages.state_changed("agent-1", %{count: 5})
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      states = Orchestrator.get_states(orch)
      assert Map.has_key?(states, "agent-1")
      assert states["agent-1"] == %{count: 5}
    end

    test "timer task_started on message received", %{orch: orch} do
      timer = Orchestrator.get_timer(orch)
      assert Timer.get_task_count(timer) == 0

      signal = OrchestratorMessages.message_received("agent-1", "msg-1")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      assert Timer.get_task_count(timer) == 1
    end

    test "timer task_completed on message processed", %{orch: orch} do
      timer = Orchestrator.get_timer(orch)

      # First receive (task_started)
      signal = OrchestratorMessages.message_received("agent-1", "msg-1")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 1

      # Then process (task_completed)
      signal = OrchestratorMessages.message_processed("agent-1", "msg-1")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 0
    end
  end

  describe "get_team/1" do
    test "returns empty team initially (no non-orchestrator agents)", %{orch: orch} do
      team = Orchestrator.get_team(orch)
      assert team == []
    end

    test "returns started agents that have not stopped", %{orch: orch} do
      signal = OrchestratorMessages.agent_started("w1", %{name: "worker-1", role: "Worker"})
      Orchestrator.record_signal(orch, signal)

      signal = OrchestratorMessages.agent_started("w2", %{name: "worker-2", role: "Worker"})
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      team = Orchestrator.get_team(orch)
      assert length(team) == 2
    end

    test "excludes stopped agents from team", %{orch: orch} do
      signal = OrchestratorMessages.agent_started("w1", %{name: "worker-1", role: "Worker"})
      Orchestrator.record_signal(orch, signal)

      signal = OrchestratorMessages.agent_stopped("w1")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      team = Orchestrator.get_team(orch)
      assert length(team) == 0
    end

    test "excludes Orchestrator from team", %{orch: orch} do
      team = Orchestrator.get_team(orch)
      assert Enum.all?(team, fn m -> m.role != "Orchestrator" end)
    end
  end

  describe "get_team_member/2" do
    test "finds team member by name", %{orch: orch} do
      signal = OrchestratorMessages.agent_started("w1", %{name: "alice", role: "Worker"})
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      member = Orchestrator.get_team_member(orch, "alice")
      assert member != nil
      assert member.name == "alice"
    end

    test "returns nil for unknown name", %{orch: orch} do
      member = Orchestrator.get_team_member(orch, "unknown")
      assert member == nil
    end
  end

  describe "subscriber notification" do
    test "notifies subscribers on events", %{orch: orch} do
      test_pid = self()

      subscriber = %{
        on_message: fn signal -> send(test_pid, {:event, signal.type}) end,
        on_stop: fn -> send(test_pid, :stopped) end
      }

      Orchestrator.subscribe(orch, subscriber)
      Process.sleep(50)

      signal = OrchestratorMessages.agent_started("w1", %{name: "w", role: "W"})
      Orchestrator.record_signal(orch, signal)

      assert_receive {:event, "akgentic.agent.started"}, 500
    end
  end

  describe "agent profile catalog" do
    test "registers and retrieves agent profiles", %{orch: orch} do
      card =
        AgentCard.new(
          role: "Worker",
          description: "Processes tasks",
          skills: ["compute"],
          agent_module: SomeModule
        )

      Orchestrator.register_agent_profile(orch, card)
      Process.sleep(50)

      profiles = Orchestrator.get_agent_catalog(orch)
      assert length(profiles) == 1
      assert hd(profiles).role == "Worker"
    end

    test "gets profile by role", %{orch: orch} do
      card =
        AgentCard.new(
          role: "Researcher",
          description: "Researches",
          skills: ["search"],
          agent_module: SomeModule
        )

      Orchestrator.register_agent_profile(orch, card)
      Process.sleep(50)

      profile = Orchestrator.get_agent_profile(orch, "Researcher")
      assert profile != nil
      assert profile.role == "Researcher"
    end

    test "finds profiles by skill", %{orch: orch} do
      card1 =
        AgentCard.new(
          role: "R1",
          description: "D1",
          skills: ["search", "analyze"],
          agent_module: SomeModule
        )

      card2 =
        AgentCard.new(
          role: "R2",
          description: "D2",
          skills: ["write"],
          agent_module: SomeModule
        )

      Orchestrator.register_agent_profile(orch, card1)
      Orchestrator.register_agent_profile(orch, card2)
      Process.sleep(50)

      results = Orchestrator.get_profiles_by_skill(orch, "search")
      assert length(results) == 1
      assert hd(results).role == "R1"
    end

    test "gets available roles", %{orch: orch} do
      card =
        AgentCard.new(
          role: "TestRole",
          description: "D",
          skills: [],
          agent_module: SomeModule
        )

      Orchestrator.register_agent_profile(orch, card)
      Process.sleep(50)

      roles = Orchestrator.get_available_roles(orch)
      assert "TestRole" in roles
    end

    test "gets available skills", %{orch: orch} do
      card1 =
        AgentCard.new(
          role: "R1",
          description: "D",
          skills: ["a", "b"],
          agent_module: SomeModule
        )

      card2 =
        AgentCard.new(
          role: "R2",
          description: "D",
          skills: ["b", "c"],
          agent_module: SomeModule
        )

      Orchestrator.register_agent_profile(orch, card1)
      Orchestrator.register_agent_profile(orch, card2)
      Process.sleep(50)

      skills = Orchestrator.get_available_skills(orch)
      assert skills == ["a", "b", "c"]
    end
  end

  describe "error message does not change task count" do
    test "ErrorMessage does not affect timer task_count", %{orch: orch} do
      timer = Orchestrator.get_timer(orch)
      assert Timer.get_task_count(timer) == 0

      signal = OrchestratorMessages.agent_error("agent-1", "Error", "boom")
      Orchestrator.record_signal(orch, signal)
      Process.sleep(50)

      # ErrorMessage should NOT change task_count
      assert Timer.get_task_count(timer) == 0
    end
  end
end
