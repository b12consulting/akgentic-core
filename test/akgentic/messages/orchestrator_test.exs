defmodule Akgentic.Messages.OrchestratorTest do
  use ExUnit.Case, async: true

  alias Akgentic.Messages.Orchestrator, as: OrchestratorMessages

  describe "signal type constants" do
    test "returns correct signal types" do
      assert OrchestratorMessages.type_agent_started() == "akgentic.agent.started"
      assert OrchestratorMessages.type_agent_stopped() == "akgentic.agent.stopped"
      assert OrchestratorMessages.type_message_sent() == "akgentic.message.sent"
      assert OrchestratorMessages.type_message_received() == "akgentic.message.received"
      assert OrchestratorMessages.type_message_processed() == "akgentic.message.processed"
      assert OrchestratorMessages.type_agent_error() == "akgentic.agent.error"
      assert OrchestratorMessages.type_state_changed() == "akgentic.agent.state_changed"
      assert OrchestratorMessages.type_agent_event() == "akgentic.agent.event"
    end
  end

  describe "agent_started/3" do
    test "creates an agent started signal" do
      signal = OrchestratorMessages.agent_started("agent-1", %{name: "worker", role: "Worker"})

      assert signal.type == "akgentic.agent.started"
      assert signal.data.agent_id == "agent-1"
      assert signal.data.config == %{name: "worker", role: "Worker"}
      assert signal.source == "/agent/agent-1"
    end

    test "accepts custom source" do
      signal =
        OrchestratorMessages.agent_started("agent-1", %{}, source: "/custom/source")

      assert signal.source == "/custom/source"
    end

    test "accepts parent option" do
      signal =
        OrchestratorMessages.agent_started("agent-1", %{}, parent: "parent-1")

      assert signal.data.parent == "parent-1"
    end
  end

  describe "agent_stopped/2" do
    test "creates an agent stopped signal" do
      signal = OrchestratorMessages.agent_stopped("agent-1")

      assert signal.type == "akgentic.agent.stopped"
      assert signal.data.agent_id == "agent-1"
    end
  end

  describe "message_sent/4" do
    test "creates a message sent signal" do
      signal =
        OrchestratorMessages.message_sent(
          "sender-1",
          %{content: "hello"},
          "recipient-1"
        )

      assert signal.type == "akgentic.message.sent"
      assert signal.data.sender_id == "sender-1"
      assert signal.data.message == %{content: "hello"}
      assert signal.data.recipient_id == "recipient-1"
    end
  end

  describe "message_received/3" do
    test "creates a message received signal" do
      signal = OrchestratorMessages.message_received("agent-1", "msg-123")

      assert signal.type == "akgentic.message.received"
      assert signal.data.agent_id == "agent-1"
      assert signal.data.message_id == "msg-123"
    end
  end

  describe "message_processed/3" do
    test "creates a message processed signal" do
      signal = OrchestratorMessages.message_processed("agent-1", "msg-123")

      assert signal.type == "akgentic.message.processed"
      assert signal.data.agent_id == "agent-1"
      assert signal.data.message_id == "msg-123"
    end
  end

  describe "agent_error/4" do
    test "creates an agent error signal" do
      signal =
        OrchestratorMessages.agent_error("agent-1", "RuntimeError", "something failed")

      assert signal.type == "akgentic.agent.error"
      assert signal.data.agent_id == "agent-1"
      assert signal.data.exception_type == "RuntimeError"
      assert signal.data.exception_value == "something failed"
    end

    test "includes current message when provided" do
      signal =
        OrchestratorMessages.agent_error(
          "agent-1",
          "RuntimeError",
          "failed",
          current_message: %{id: "msg-1"}
        )

      assert signal.data.current_message == %{id: "msg-1"}
    end
  end

  describe "state_changed/3" do
    test "creates a state changed signal" do
      signal =
        OrchestratorMessages.state_changed("agent-1", %{tasks_completed: 5})

      assert signal.type == "akgentic.agent.state_changed"
      assert signal.data.agent_id == "agent-1"
      assert signal.data.state == %{tasks_completed: 5}
    end
  end

  describe "agent_event/3" do
    test "creates an agent event signal" do
      signal = OrchestratorMessages.agent_event("agent-1", %{type: "custom", value: 42})

      assert signal.type == "akgentic.agent.event"
      assert signal.data.agent_id == "agent-1"
      assert signal.data.event == %{type: "custom", value: 42}
    end
  end
end
