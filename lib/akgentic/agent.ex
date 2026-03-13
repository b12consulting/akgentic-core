defmodule Akgentic.Agent do
  @moduledoc """
  Base agent macro for defining Akgentic agents using Jido.

  This module provides the `use Akgentic.Agent` macro that wraps `Jido.Agent`
  with Akgentic-specific conventions and helpers. It maps the original Python
  `Akgent` class to Jido's pure functional agent pattern.

  ## Python → Elixir Mapping

  | Python `Akgent`                 | Elixir `Akgentic.Agent`           |
  |---------------------------------|-----------------------------------|
  | `receiveMsg_<Type>` handlers    | `signal_routes` + `Jido.Action`   |
  | `self.state`                    | `agent.state`                     |
  | `self.config`                   | Agent schema fields               |
  | `self.send(recipient, msg)`     | Emit directive / signal routing   |
  | `self.createActor(class, cfg)`  | SpawnAgent directive              |
  | `self.myAddress`                | `self()` / PID                    |
  | `on_start()`                    | `on_start/1` callback             |
  | `on_stop()`                     | `on_stop/1` callback              |

  ## Example

      defmodule MyApp.GreeterAgent do
        use Akgentic.Agent,
          name: "greeter",
          description: "Sends greeting messages",
          schema: [
            greeting_count: [type: :integer, default: 0]
          ],
          actions: [MyApp.Actions.Greet],
          signal_routes: [
            {"greet", MyApp.Actions.Greet}
          ]
      end

  ## Agent Lifecycle

  Agents are created as immutable data structures with `new/1`:

      agent = MyApp.GreeterAgent.new()

  State changes are performed via `cmd/2`:

      {agent, directives} = MyApp.GreeterAgent.cmd(agent, {MyApp.Actions.Greet, %{name: "World"}})

  For production use, agents run inside `Jido.AgentServer` processes:

      {:ok, pid} = Akgentic.start_agent(MyApp.GreeterAgent, id: "greeter-1")
      {:ok, agent} = Akgentic.signal(pid, "greet", %{name: "World"})
  """

  @doc """
  Defines an Akgentic agent using `Jido.Agent` under the hood.

  Accepts the same options as `Jido.Agent` plus Akgentic-specific options.

  ## Options

    * `:name` - Agent name (required)
    * `:description` - Human-readable description (required)
    * `:schema` - NimbleOptions schema for agent state
    * `:actions` - List of action modules this agent can execute
    * `:signal_routes` - List of `{signal_type, action_module}` tuples
    * `:role` - Agent role for categorization (defaults to module name)

  """
  defmacro __using__(opts) do
    role = Keyword.get(opts, :role, nil)
    enhanced_opts = Keyword.put_new(opts, :role, role)

    quote do
      use Jido.Agent, unquote(enhanced_opts)

      @doc """
      Returns the role of this agent.
      """
      def role do
        unquote(role) || __MODULE__ |> Module.split() |> List.last()
      end
    end
  end
end
