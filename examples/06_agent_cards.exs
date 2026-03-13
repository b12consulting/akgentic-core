# Agent Cards — Capability Discovery and Routing
#
# This example demonstrates the AgentCard catalog pattern:
# - Defining agent profiles with roles, skills, and routing permissions
# - Registering profiles with the Orchestrator catalog
# - Discovering agents by role or skill
# - Checking routing permissions between agents
#
# Maps from Python's AgentCard catalog registration, discovery by role/skill,
# and routing permissions.
#
# Run with: mix run examples/06_agent_cards.exs

alias Akgentic.AgentCard
alias Akgentic.Orchestrator

# =============================================================================
# STEP 1: Create AgentCards describing available agent roles
# =============================================================================

IO.puts("\n=== AgentCard Creation ===\n")

researcher_card =
  AgentCard.new(
    role: "ResearchAgent",
    description: "Researches topics using web search and data extraction",
    skills: ["web_search", "pdf_extraction", "summarization"],
    agent_module: "MyApp.ResearchAgent",
    config: %{name: "researcher", role: "ResearchAgent"},
    routes_to: ["WriterAgent", "AnalystAgent"],
    metadata: %{version: "1.0", max_concurrent_tasks: 3}
  )

writer_card =
  AgentCard.new(
    role: "WriterAgent",
    description: "Writes articles and reports from research findings",
    skills: ["article_writing", "summarization", "formatting"],
    agent_module: "MyApp.WriterAgent",
    config: %{name: "writer", role: "WriterAgent"},
    routes_to: ["ReviewerAgent"],
    metadata: %{version: "1.0"}
  )

analyst_card =
  AgentCard.new(
    role: "AnalystAgent",
    description: "Analyzes data and produces insights",
    skills: ["data_analysis", "visualization", "statistical_modeling"],
    agent_module: "MyApp.AnalystAgent",
    config: %{name: "analyst", role: "AnalystAgent"},
    routes_to: [],
    metadata: %{version: "2.0"}
  )

IO.puts("Created agent cards:")
IO.puts("  - #{researcher_card.role}: #{length(researcher_card.skills)} skills")
IO.puts("  - #{writer_card.role}: #{length(writer_card.skills)} skills")
IO.puts("  - #{analyst_card.role}: #{length(analyst_card.skills)} skills")

# =============================================================================
# STEP 2: Register cards in the Orchestrator catalog
# =============================================================================

IO.puts("\n=== Registering Profiles with Orchestrator ===\n")

{:ok, orch} = Orchestrator.start_link(name: "catalog-orch", timeout_delay: 3600)

Orchestrator.register_agent_profiles(orch, [researcher_card, writer_card, analyst_card])
Process.sleep(100)

catalog = Orchestrator.get_agent_catalog(orch)
IO.puts("Registered #{length(catalog)} agent profiles in the catalog")

# =============================================================================
# STEP 3: Discover agents by role or skill
# =============================================================================

IO.puts("\n=== Discovery: Lookup by Role ===\n")

profile = Orchestrator.get_agent_profile(orch, "WriterAgent")
IO.puts("Found '#{profile.role}': #{profile.description}")
IO.puts("Skills: #{Enum.join(profile.skills, ", ")}")

IO.puts("\n=== Discovery: Lookup by Skill ===\n")

summarizers = Orchestrator.get_profiles_by_skill(orch, "summarization")
IO.puts("Agents with 'summarization' skill:")

Enum.each(summarizers, fn p ->
  IO.puts("  - #{p.role}")
end)

web_searchers = Orchestrator.get_profiles_by_skill(orch, "web_search")
IO.puts("\nAgents with 'web_search' skill:")

Enum.each(web_searchers, fn p ->
  IO.puts("  - #{p.role}")
end)

IO.puts("\n=== Discovery: Available Roles and Skills ===\n")

roles = Orchestrator.get_available_roles(orch)
IO.puts("All available roles: #{Enum.join(roles, ", ")}")

skills = Orchestrator.get_available_skills(orch)
IO.puts("All available skills: #{Enum.join(skills, ", ")}")

# =============================================================================
# STEP 4: Check routing permissions
# =============================================================================

IO.puts("\n=== Routing Permissions ===\n")

IO.puts("ResearchAgent → WriterAgent: #{AgentCard.can_route_to?(researcher_card, "WriterAgent")}")
IO.puts("ResearchAgent → AnalystAgent: #{AgentCard.can_route_to?(researcher_card, "AnalystAgent")}")
IO.puts("ResearchAgent → ReviewerAgent: #{AgentCard.can_route_to?(researcher_card, "ReviewerAgent")}")

IO.puts("WriterAgent → ReviewerAgent: #{AgentCard.can_route_to?(writer_card, "ReviewerAgent")}")
IO.puts("WriterAgent → ResearchAgent: #{AgentCard.can_route_to?(writer_card, "ResearchAgent")}")

# AnalystAgent has empty routes_to — it can route to anyone
IO.puts("AnalystAgent → AnyRole (unrestricted): #{AgentCard.can_route_to?(analyst_card, "AnyRole")}")

# =============================================================================
# STEP 5: Get config copy for safe agent instantiation
# =============================================================================

IO.puts("\n=== Safe Config Copies ===\n")

config = AgentCard.get_config_copy(researcher_card)
IO.puts("Config copy for ResearchAgent: #{inspect(config)}")

module = AgentCard.get_agent_module(researcher_card)
IO.puts("Agent module (from string): #{inspect(module)}")

# Serialize to/from map
map = AgentCard.to_map(writer_card)
IO.puts("\nSerialized WriterAgent card:")
IO.inspect(map, pretty: true)

Orchestrator.stop(orch)

IO.puts("\n[Agent Cards] Done!")
