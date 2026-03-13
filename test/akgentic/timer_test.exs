defmodule Akgentic.TimerTest do
  use ExUnit.Case, async: true

  alias Akgentic.Timer

  describe "start_link/1" do
    test "starts the timer process" do
      {:ok, pid} = Timer.start_link(delay: 60, on_timeout: fn -> :ok end)
      assert Process.alive?(pid)
      GenServer.stop(pid)
    end
  end

  describe "task_started/1 and task_completed/1" do
    test "increments and decrements task count" do
      {:ok, pid} = Timer.start_link(delay: 60, on_timeout: fn -> :ok end)

      assert Timer.get_task_count(pid) == 0

      Timer.task_started(pid)
      # Give the cast time to process
      Process.sleep(10)
      assert Timer.get_task_count(pid) == 1

      Timer.task_started(pid)
      Process.sleep(10)
      assert Timer.get_task_count(pid) == 2

      Timer.task_completed(pid)
      Process.sleep(10)
      assert Timer.get_task_count(pid) == 1

      Timer.task_completed(pid)
      Process.sleep(10)
      assert Timer.get_task_count(pid) == 0

      GenServer.stop(pid)
    end

    test "task_count does not go below zero" do
      {:ok, pid} = Timer.start_link(delay: 60, on_timeout: fn -> :ok end)

      Timer.task_completed(pid)
      Process.sleep(10)
      assert Timer.get_task_count(pid) == 0

      Timer.task_completed(pid)
      Process.sleep(10)
      assert Timer.get_task_count(pid) == 0

      GenServer.stop(pid)
    end
  end

  describe "timeout callback" do
    test "fires after delay when idle" do
      test_pid = self()

      {:ok, pid} =
        Timer.start_link(
          delay: 1,
          on_timeout: fn -> send(test_pid, :timeout_fired) end
        )

      Timer.start_countdown(pid)

      # Should fire within ~1 second
      assert_receive :timeout_fired, 2_000

      GenServer.stop(pid)
    end

    test "does not fire while tasks are active" do
      test_pid = self()

      {:ok, pid} =
        Timer.start_link(
          delay: 1,
          on_timeout: fn -> send(test_pid, :timeout_fired) end
        )

      Timer.start_countdown(pid)
      Timer.task_started(pid)

      # Should NOT fire because task is active
      refute_receive :timeout_fired, 1_500

      GenServer.stop(pid)
    end

    test "fires after task completes and delay passes" do
      test_pid = self()

      {:ok, pid} =
        Timer.start_link(
          delay: 1,
          on_timeout: fn -> send(test_pid, :timeout_fired) end
        )

      Timer.task_started(pid)
      Process.sleep(100)

      # Complete the task - should restart countdown
      Timer.task_completed(pid)

      # Should fire within ~1 second
      assert_receive :timeout_fired, 2_000

      GenServer.stop(pid)
    end

    test "cancel prevents callback from firing" do
      test_pid = self()

      {:ok, pid} =
        Timer.start_link(
          delay: 1,
          on_timeout: fn -> send(test_pid, :timeout_fired) end
        )

      Timer.start_countdown(pid)
      Process.sleep(100)
      Timer.cancel(pid)

      refute_receive :timeout_fired, 1_500

      GenServer.stop(pid)
    end
  end

  describe "get_delay/1" do
    test "returns the configured delay" do
      {:ok, pid} = Timer.start_link(delay: 42, on_timeout: fn -> :ok end)
      assert Timer.get_delay(pid) == 42
      GenServer.stop(pid)
    end
  end
end
