defmodule Akgentic.IntegrationTest do
  @moduledoc """
  Full end-to-end Orchestrator inactivity timer integration tests.
  Port of tests/test_epic3_integration.py from the Python akgentic codebase.

  Tests the complete Orchestrator + Timer lifecycle:
  - message_received pauses the timer (task_count increments)
  - message_processed restarts the timer (task_count decrements)
  - Orchestrator stops after timeout when idle
  - Manual stop cancels timer cleanly
  - Multiple receive/process cycles reset timer correctly
  """

  use ExUnit.Case, async: true

  alias Akgentic.Messages.Orchestrator, as: OrchestratorMessages
  alias Akgentic.Orchestrator
  alias Akgentic.Timer

  # Helper to create a uniquely-named orchestrator per test
  defp start_orch(opts \\ []) do
    name = "integration-#{System.unique_integer([:positive])}"
    defaults = [name: name, timeout_delay: 3600]
    Orchestrator.start_link(Keyword.merge(defaults, opts))
  end

  describe "message_received signal pauses the inactivity timer" do
    test "task_count increments on each message_received" do
      {:ok, orch} = start_orch()
      timer = Orchestrator.get_timer(orch)

      assert Timer.get_task_count(timer) == 0

      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-1", "msg-1"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 1

      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-1", "msg-2"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 2

      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-2", "msg-3"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 3

      Orchestrator.stop(orch)
    end
  end

  describe "message_processed signal restarts the inactivity timer" do
    test "task_count decrements on each message_processed" do
      {:ok, orch} = start_orch()
      timer = Orchestrator.get_timer(orch)

      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-1", "msg-1"))
      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-1", "msg-2"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 2

      Orchestrator.record_signal(
        orch,
        OrchestratorMessages.message_processed("agent-1", "msg-1")
      )

      Process.sleep(50)
      assert Timer.get_task_count(timer) == 1

      Orchestrator.record_signal(
        orch,
        OrchestratorMessages.message_processed("agent-1", "msg-2")
      )

      Process.sleep(50)
      assert Timer.get_task_count(timer) == 0

      Orchestrator.stop(orch)
    end

    test "timer restarts countdown when task_count reaches zero" do
      {:ok, orch} = start_orch(timeout_delay: 1)
      timer = Orchestrator.get_timer(orch)

      # Monitor the orchestrator so we can detect when it stops
      ref = Process.monitor(orch)

      # Pause the timer with an active task
      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-1", "msg-1"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 1

      # Complete the task — timer restarts with 1-second delay
      Orchestrator.record_signal(
        orch,
        OrchestratorMessages.message_processed("agent-1", "msg-1")
      )

      Process.sleep(50)
      assert Timer.get_task_count(timer) == 0

      # Orchestrator should stop after the 1-second timeout
      assert_receive {:DOWN, ^ref, :process, ^orch, :normal}, 3_000
    end
  end

  describe "orchestrator stops after timeout when idle" do
    test "stops with :normal after timeout_delay elapses" do
      {:ok, orch} = start_orch(timeout_delay: 1)
      ref = Process.monitor(orch)

      # Orchestrator starts countdown immediately on init
      # Should stop after ~1 second of inactivity
      assert_receive {:DOWN, ^ref, :process, ^orch, :normal}, 3_000
    end

    test "does not stop while tasks are active" do
      {:ok, orch} = start_orch(timeout_delay: 1)
      ref = Process.monitor(orch)

      # Keep the timer busy with an active task
      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("agent-1", "msg-1"))
      Process.sleep(50)

      # Should NOT stop within the timeout period because task_count > 0
      refute_receive {:DOWN, ^ref, :process, ^orch, :normal}, 1_500

      # Complete the task and allow the orchestrator to stop normally
      Orchestrator.stop(orch)
    end
  end

  describe "manual stop cancels timer cleanly" do
    test "Orchestrator.stop/1 stops the process with :normal reason" do
      {:ok, orch} = start_orch()
      ref = Process.monitor(orch)

      assert Process.alive?(orch)
      Orchestrator.stop(orch)

      assert_receive {:DOWN, ^ref, :process, ^orch, :normal}, 1_000
    end

    test "stop/1 cancels the inactivity timer" do
      {:ok, orch} = start_orch()
      timer = Orchestrator.get_timer(orch)

      assert Process.alive?(timer)
      Orchestrator.stop(orch)
      Process.sleep(100)

      # Timer process should have been stopped by the orchestrator terminate callback
      refute Process.alive?(timer)
    end
  end

  describe "multiple receive/process cycles reset timer correctly" do
    test "task_count returns to zero after each completed cycle" do
      {:ok, orch} = start_orch()
      timer = Orchestrator.get_timer(orch)

      Enum.each(1..3, fn i ->
        msg_id = "msg-#{i}"

        Orchestrator.record_signal(
          orch,
          OrchestratorMessages.message_received("agent-1", msg_id)
        )

        Process.sleep(50)
        assert Timer.get_task_count(timer) == 1

        Orchestrator.record_signal(
          orch,
          OrchestratorMessages.message_processed("agent-1", msg_id)
        )

        Process.sleep(50)
        assert Timer.get_task_count(timer) == 0
      end)

      Orchestrator.stop(orch)
    end

    test "interleaved receives and processes track count accurately" do
      {:ok, orch} = start_orch()
      timer = Orchestrator.get_timer(orch)

      # Two concurrent tasks
      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("a", "m1"))
      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("b", "m2"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 2

      # One completes
      Orchestrator.record_signal(orch, OrchestratorMessages.message_processed("a", "m1"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 1

      # Third task arrives
      Orchestrator.record_signal(orch, OrchestratorMessages.message_received("c", "m3"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 2

      # Both remaining complete
      Orchestrator.record_signal(orch, OrchestratorMessages.message_processed("b", "m2"))
      Orchestrator.record_signal(orch, OrchestratorMessages.message_processed("c", "m3"))
      Process.sleep(50)
      assert Timer.get_task_count(timer) == 0

      Orchestrator.stop(orch)
    end
  end

  describe "error signals do not affect the timer" do
    test "agent_error signals do not change task_count" do
      {:ok, orch} = start_orch()
      timer = Orchestrator.get_timer(orch)

      assert Timer.get_task_count(timer) == 0

      Orchestrator.record_signal(
        orch,
        OrchestratorMessages.agent_error("agent-1", "RuntimeError", "something failed")
      )

      Process.sleep(50)
      assert Timer.get_task_count(timer) == 0

      Orchestrator.stop(orch)
    end
  end
end
