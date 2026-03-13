defmodule Akgentic.AgentCard do
  @moduledoc """
  Agent profile cards for team capability discovery.

  AgentCards describe available agent profiles/roles in a team, enabling
  dynamic discovery of capabilities and agent creation patterns.

  ## Python → Elixir Mapping

  Maps from Python's `AgentCard(SerializableBaseModel)` to an Elixir struct
  with equivalent fields and functions.

  ## Examples

      card = Akgentic.AgentCard.new(
        role: "ResearchAgent",
        description: "Performs web research and data gathering",
        skills: ["web_search", "pdf_extraction"],
        agent_module: MyApp.ResearchAgent,
        config: %{name: "research", role: "ResearchAgent"},
        routes_to: ["WriterAgent", "AnalystAgent"]
      )

      card.skills
      # => ["web_search", "pdf_extraction"]

      Akgentic.AgentCard.has_skill?(card, "web_search")
      # => true

      Akgentic.AgentCard.can_route_to?(card, "WriterAgent")
      # => true
  """

  @type t :: %__MODULE__{
          role: String.t(),
          description: String.t(),
          skills: [String.t()],
          agent_module: module() | String.t(),
          config: map(),
          routes_to: [String.t()],
          metadata: map()
        }

  @enforce_keys [:role, :description, :skills, :agent_module]
  defstruct [
    :role,
    :description,
    :skills,
    :agent_module,
    config: %{},
    routes_to: [],
    metadata: %{}
  ]

  @doc """
  Create a new AgentCard.

  ## Options

    * `:role` - Agent role/type identifier (required)
    * `:description` - Human-readable description (required)
    * `:skills` - List of capabilities (required)
    * `:agent_module` - Module or string for agent class (required)
    * `:config` - Default configuration map (default: %{})
    * `:routes_to` - List of roles this agent can send to (default: [])
    * `:metadata` - Extensible key-value storage (default: %{})

  ## Examples

      card = Akgentic.AgentCard.new(
        role: "Worker",
        description: "Processes tasks",
        skills: ["compute"],
        agent_module: MyApp.WorkerAgent
      )
  """
  @spec new(keyword()) :: t()
  def new(opts) do
    struct!(__MODULE__, opts)
  end

  @doc """
  Get a deep copy of the config map.

  Always use this method when creating agents from an AgentCard
  to prevent shared mutable state.

  ## Examples

      config = Akgentic.AgentCard.get_config_copy(card)
  """
  @spec get_config_copy(t()) :: map()
  def get_config_copy(%__MODULE__{config: config}) do
    # Deep copy via serialization round-trip
    config
    |> :erlang.term_to_binary()
    |> :erlang.binary_to_term()
  end

  @doc """
  Get the agent module as a module atom.

  If `agent_module` is a string, it is converted to a module atom.

  ## Examples

      module = Akgentic.AgentCard.get_agent_module(card)
  """
  @spec get_agent_module(t()) :: module()
  def get_agent_module(%__MODULE__{agent_module: module}) when is_atom(module), do: module

  def get_agent_module(%__MODULE__{agent_module: module_string}) when is_binary(module_string) do
    module_string
    |> String.split(".")
    |> Enum.map(&String.to_existing_atom/1)
    |> Module.concat()
  end

  @doc """
  Check if this profile has a specific skill.

  ## Examples

      Akgentic.AgentCard.has_skill?(card, "web_search")
      # => true
  """
  @spec has_skill?(t(), String.t()) :: boolean()
  def has_skill?(%__MODULE__{skills: skills}, skill) do
    skill in skills
  end

  @doc """
  Check if this profile can send requests to a specific role.

  An empty `routes_to` list means no restrictions (can route to anyone).
  Otherwise, the target role must be in the `routes_to` list.

  Note: Agents can always respond to requests from any role.
  This only controls which roles an agent can proactively send to.

  ## Examples

      Akgentic.AgentCard.can_route_to?(card, "WriterAgent")
      # => true
  """
  @spec can_route_to?(t(), String.t()) :: boolean()
  def can_route_to?(%__MODULE__{routes_to: []}, _role), do: true
  def can_route_to?(%__MODULE__{routes_to: routes_to}, role), do: role in routes_to

  @doc """
  Serialize the agent card to a map.

  ## Examples

      map = Akgentic.AgentCard.to_map(card)
  """
  @spec to_map(t()) :: map()
  def to_map(%__MODULE__{} = card) do
    agent_module =
      case card.agent_module do
        module when is_atom(module) -> inspect(module)
        string when is_binary(string) -> string
      end

    %{
      role: card.role,
      description: card.description,
      skills: card.skills,
      agent_module: agent_module,
      config: card.config,
      routes_to: card.routes_to,
      metadata: card.metadata
    }
  end

  @doc """
  Deserialize an agent card from a map.

  ## Examples

      card = Akgentic.AgentCard.from_map(map)
  """
  @spec from_map(map()) :: t()
  def from_map(map) when is_map(map) do
    %__MODULE__{
      role: Map.fetch!(map, :role),
      description: Map.fetch!(map, :description),
      skills: Map.get(map, :skills, []),
      agent_module: Map.fetch!(map, :agent_module),
      config: Map.get(map, :config, %{}),
      routes_to: Map.get(map, :routes_to, []),
      metadata: Map.get(map, :metadata, %{})
    }
  end
end
