defmodule Akgentic.PublicAPITest do
  use ExUnit.Case, async: true

  @moduledoc """
  Verifies that all public modules and their key functions are accessible.
  Port of tests/test_public_api.py from the Python akgentic codebase.
  """

  describe "Akgentic top-level module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic)
    end

    test "version/0 returns the current version string" do
      version = Akgentic.version()
      assert is_binary(version)
      assert version == "1.0.0-alpha.1"
    end

    test "exports start_agent/2" do
      assert function_exported?(Akgentic, :start_agent, 2)
    end

    test "exports signal/4" do
      assert function_exported?(Akgentic, :signal, 4)
    end

    test "exports signal_async/4" do
      assert function_exported?(Akgentic, :signal_async, 4)
    end

    test "exports stop_agent/1" do
      assert function_exported?(Akgentic, :stop_agent, 1)
    end
  end

  describe "Akgentic.Agent module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.Agent)
    end
  end

  describe "Akgentic.Signal module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.Signal)
    end

    test "exports new/3" do
      assert function_exported?(Akgentic.Signal, :new, 3)
    end
  end

  describe "Akgentic.Timer module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.Timer)
    end

    test "exports start_link/1" do
      assert function_exported?(Akgentic.Timer, :start_link, 1)
    end

    test "exports start_countdown/1" do
      assert function_exported?(Akgentic.Timer, :start_countdown, 1)
    end

    test "exports cancel/1" do
      assert function_exported?(Akgentic.Timer, :cancel, 1)
    end

    test "exports task_started/1" do
      assert function_exported?(Akgentic.Timer, :task_started, 1)
    end

    test "exports task_completed/1" do
      assert function_exported?(Akgentic.Timer, :task_completed, 1)
    end

    test "exports get_task_count/1" do
      assert function_exported?(Akgentic.Timer, :get_task_count, 1)
    end
  end

  describe "Akgentic.AgentCard module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.AgentCard)
    end

    test "exports new/1" do
      assert function_exported?(Akgentic.AgentCard, :new, 1)
    end

    test "exports has_skill?/2" do
      assert function_exported?(Akgentic.AgentCard, :has_skill?, 2)
    end

    test "exports can_route_to?/2" do
      assert function_exported?(Akgentic.AgentCard, :can_route_to?, 2)
    end

    test "exports get_config_copy/1" do
      assert function_exported?(Akgentic.AgentCard, :get_config_copy, 1)
    end

    test "exports get_agent_module/1" do
      assert function_exported?(Akgentic.AgentCard, :get_agent_module, 1)
    end

    test "exports to_map/1" do
      assert function_exported?(Akgentic.AgentCard, :to_map, 1)
    end

    test "exports from_map/1" do
      assert function_exported?(Akgentic.AgentCard, :from_map, 1)
    end
  end

  describe "Akgentic.Orchestrator module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.Orchestrator)
    end

    test "exports start_link/1" do
      assert function_exported?(Akgentic.Orchestrator, :start_link, 1)
    end

    test "exports record_signal/2" do
      assert function_exported?(Akgentic.Orchestrator, :record_signal, 2)
    end

    test "exports subscribe/2" do
      assert function_exported?(Akgentic.Orchestrator, :subscribe, 2)
    end

    test "exports get_messages/1" do
      assert function_exported?(Akgentic.Orchestrator, :get_messages, 1)
    end

    test "exports get_team/1" do
      assert function_exported?(Akgentic.Orchestrator, :get_team, 1)
    end

    test "exports get_agent_catalog/1" do
      assert function_exported?(Akgentic.Orchestrator, :get_agent_catalog, 1)
    end

    test "exports register_agent_profile/2" do
      assert function_exported?(Akgentic.Orchestrator, :register_agent_profile, 2)
    end

    test "exports get_profiles_by_skill/2" do
      assert function_exported?(Akgentic.Orchestrator, :get_profiles_by_skill, 2)
    end

    test "exports stop/1" do
      assert function_exported?(Akgentic.Orchestrator, :stop, 1)
    end
  end

  describe "Akgentic.UserProxy module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.UserProxy)
    end

    test "exports start_link/1" do
      assert function_exported?(Akgentic.UserProxy, :start_link, 1)
    end

    test "exports receive_message/2" do
      assert function_exported?(Akgentic.UserProxy, :receive_message, 2)
    end

    test "exports process_human_input/3" do
      assert function_exported?(Akgentic.UserProxy, :process_human_input, 3)
    end

    test "exports get_pending_messages/1" do
      assert function_exported?(Akgentic.UserProxy, :get_pending_messages, 1)
    end

    test "exports clear_pending/1" do
      assert function_exported?(Akgentic.UserProxy, :clear_pending, 1)
    end
  end

  describe "Akgentic.EventSubscriber module" do
    test "is accessible" do
      assert Code.ensure_loaded?(Akgentic.EventSubscriber)
    end

    test "exports invoke_on_stop/1" do
      assert function_exported?(Akgentic.EventSubscriber, :invoke_on_stop, 1)
    end

    test "exports invoke_on_message/2" do
      assert function_exported?(Akgentic.EventSubscriber, :invoke_on_message, 2)
    end
  end
end
