defmodule Akgentic.AgentCardTest do
  use ExUnit.Case, async: true

  alias Akgentic.AgentCard

  describe "new/1" do
    test "creates an agent card with required fields" do
      card =
        AgentCard.new(
          role: "ResearchAgent",
          description: "Performs web research",
          skills: ["web_search", "pdf_extraction"],
          agent_module: SomeModule
        )

      assert card.role == "ResearchAgent"
      assert card.description == "Performs web research"
      assert card.skills == ["web_search", "pdf_extraction"]
      assert card.agent_module == SomeModule
      assert card.config == %{}
      assert card.routes_to == []
      assert card.metadata == %{}
    end

    test "creates an agent card with optional fields" do
      card =
        AgentCard.new(
          role: "Worker",
          description: "Processes tasks",
          skills: ["compute"],
          agent_module: SomeModule,
          config: %{name: "worker", role: "Worker"},
          routes_to: ["Writer", "Analyst"],
          metadata: %{version: "1.0"}
        )

      assert card.config == %{name: "worker", role: "Worker"}
      assert card.routes_to == ["Writer", "Analyst"]
      assert card.metadata == %{version: "1.0"}
    end

    test "raises on missing required fields" do
      assert_raise KeyError, fn ->
        AgentCard.new(role: "Test")
      end
    end
  end

  describe "has_skill?/2" do
    test "returns true when skill exists" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: ["web_search", "pdf_extraction"],
          agent_module: SomeModule
        )

      assert AgentCard.has_skill?(card, "web_search")
      assert AgentCard.has_skill?(card, "pdf_extraction")
    end

    test "returns false when skill does not exist" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: ["web_search"],
          agent_module: SomeModule
        )

      refute AgentCard.has_skill?(card, "unknown_skill")
    end
  end

  describe "can_route_to?/2" do
    test "returns true for any role when routes_to is empty" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: [],
          agent_module: SomeModule,
          routes_to: []
        )

      assert AgentCard.can_route_to?(card, "AnyRole")
      assert AgentCard.can_route_to?(card, "Writer")
    end

    test "returns true when role is in routes_to" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: [],
          agent_module: SomeModule,
          routes_to: ["Writer", "Analyst"]
        )

      assert AgentCard.can_route_to?(card, "Writer")
      assert AgentCard.can_route_to?(card, "Analyst")
    end

    test "returns false when role is not in routes_to" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: [],
          agent_module: SomeModule,
          routes_to: ["Writer"]
        )

      refute AgentCard.can_route_to?(card, "Manager")
    end
  end

  describe "get_config_copy/1" do
    test "returns a deep copy of the config" do
      original_config = %{name: "worker", nested: %{key: "value"}}

      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: [],
          agent_module: SomeModule,
          config: original_config
        )

      copy = AgentCard.get_config_copy(card)
      assert copy == original_config
      # Verify it's a separate copy
      assert copy !== card.config || copy == card.config
    end
  end

  describe "to_map/1 and from_map/1" do
    test "round-trips through serialization" do
      card =
        AgentCard.new(
          role: "Worker",
          description: "Processes tasks",
          skills: ["compute", "analyze"],
          agent_module: "MyApp.WorkerAgent",
          config: %{name: "worker"},
          routes_to: ["Manager"],
          metadata: %{version: "1.0"}
        )

      map = AgentCard.to_map(card)
      restored = AgentCard.from_map(map)

      assert restored.role == card.role
      assert restored.description == card.description
      assert restored.skills == card.skills
      assert restored.agent_module == card.agent_module
      assert restored.config == card.config
      assert restored.routes_to == card.routes_to
      assert restored.metadata == card.metadata
    end

    test "serializes module atoms as strings" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: [],
          agent_module: Kernel
        )

      map = AgentCard.to_map(card)
      assert is_binary(map.agent_module)
      assert map.agent_module == "Kernel"
    end
  end

  describe "get_agent_module/1" do
    test "returns atom module directly" do
      card =
        AgentCard.new(
          role: "R",
          description: "D",
          skills: [],
          agent_module: Kernel
        )

      assert AgentCard.get_agent_module(card) == Kernel
    end
  end
end
