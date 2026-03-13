# Hello World - Basic Agent Example
#
# This example demonstrates the core Akgentic pattern using Jido:
# - Defining actions that transform agent state
# - Defining agents with schemas and signal routes
# - Creating and interacting with agents
#
# Run with: mix run examples/01_hello_world.exs

# =============================================================================
# STEP 1: Define an action
# =============================================================================
# Actions are pure functions that take params and context, and return
# state updates. They replace the Python receiveMsg_<Type> pattern.

defmodule Examples.Actions.Echo do
  @moduledoc "Echoes a message by storing it in agent state."
  use Jido.Action,
    name: "echo",
    description: "Echoes a message",
    schema: [
      content: [type: :string, required: true]
    ]

  def run(params, _context) do
    IO.puts("[EchoAgent] Received: #{params.content}")
    {:ok, %{last_echo: params.content}}
  end
end

# =============================================================================
# STEP 2: Define an agent
# =============================================================================
# Agents use `use Akgentic.Agent` (which wraps `Jido.Agent`).
# The schema defines typed state, and signal_routes map signal types
# to action modules.

defmodule Examples.EchoAgent do
  @moduledoc "An agent that echoes messages."
  use Akgentic.Agent,
    name: "echo_agent",
    description: "An agent that echoes messages",
    schema: [
      last_echo: [type: :string, default: ""]
    ],
    actions: [Examples.Actions.Echo],
    signal_routes: [
      {"echo", Examples.Actions.Echo}
    ]
end

# =============================================================================
# STEP 3: Use the agent
# =============================================================================

IO.puts("[Hello World] Starting echo agent example...")

# Create an agent (pure data structure)
agent = Examples.EchoAgent.new()
IO.puts("[Hello World] Agent created: #{agent.name}")

# Execute an action directly (pure function, no process needed)
{agent, _directives} = Examples.EchoAgent.cmd(agent, {Examples.Actions.Echo, %{content: "Hello, Akgentic!"}})

IO.puts("[Hello World] Agent state after echo: last_echo = #{agent.state.last_echo}")
IO.puts("[Hello World] Done!")
