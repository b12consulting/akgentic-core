# Request/Response Patterns — Blocking vs Fire-and-Forget
#
# This example demonstrates two communication patterns between agents:
#
# 1. Fire-and-forget (async): `Akgentic.signal_async/3`
#    Maps to Python's `proxy_tell()` — send a signal and continue immediately.
#
# 2. Blocking request-response (sync): `Akgentic.signal/3`
#    Maps to Python's `proxy_ask()` — send a signal and wait for the result.
#
# Run with: mix run examples/02_request_response.exs

# =============================================================================
# STEP 1: Define actions
# =============================================================================

defmodule Examples.RequestResponse.Actions.Add do
  @moduledoc "Adds two numbers and stores the result."
  use Jido.Action,
    name: "add",
    description: "Adds two numbers",
    schema: [
      a: [type: :float, required: true],
      b: [type: :float, required: true]
    ]

  def run(%{a: a, b: b}, _context) do
    result = a + b
    IO.puts("[CalculatorAgent] add(#{a}, #{b}) = #{result}")
    {:ok, %{last_result: result, last_operation: "add"}}
  end
end

defmodule Examples.RequestResponse.Actions.Multiply do
  @moduledoc "Multiplies two numbers and stores the result."
  use Jido.Action,
    name: "multiply",
    description: "Multiplies two numbers",
    schema: [
      a: [type: :float, required: true],
      b: [type: :float, required: true]
    ]

  def run(%{a: a, b: b}, _context) do
    result = a * b
    IO.puts("[CalculatorAgent] multiply(#{a}, #{b}) = #{result}")
    {:ok, %{last_result: result, last_operation: "multiply"}}
  end
end

# =============================================================================
# STEP 2: Define the CalculatorAgent
# =============================================================================

defmodule Examples.RequestResponse.CalculatorAgent do
  @moduledoc "An agent that performs arithmetic operations."
  use Akgentic.Agent,
    name: "calculator",
    description: "Performs arithmetic operations",
    schema: [
      last_result: [type: :float, default: 0.0],
      last_operation: [type: :string, default: ""]
    ],
    actions: [
      Examples.RequestResponse.Actions.Add,
      Examples.RequestResponse.Actions.Multiply
    ],
    signal_routes: [
      {"add", Examples.RequestResponse.Actions.Add},
      {"multiply", Examples.RequestResponse.Actions.Multiply}
    ]
end

# =============================================================================
# STEP 3: Pure functional path — cmd/2 (synchronous, no OTP process needed)
# =============================================================================

IO.puts("\n=== Pure Functional Path (cmd/2) ===\n")

alias Examples.RequestResponse.Actions.Add
alias Examples.RequestResponse.Actions.Multiply
alias Examples.RequestResponse.CalculatorAgent

agent = CalculatorAgent.new()
IO.puts("Initial state: last_result=#{agent.state.last_result}")

{agent, _directives} = CalculatorAgent.cmd(agent, {Add, %{a: 10.0, b: 5.0}})
IO.puts("After add(10, 5): last_result=#{agent.state.last_result}")

{agent, _directives} = CalculatorAgent.cmd(agent, {Multiply, %{a: 4.0, b: 7.0}})
IO.puts("After multiply(4, 7): last_result=#{agent.state.last_result}")

# =============================================================================
# STEP 4: OTP path — blocking (signal/3) vs fire-and-forget (signal_async/3)
# =============================================================================

IO.puts("\n=== OTP Path: Blocking (signal/3) ===\n")

# Start the agent under the OTP supervisor
{:ok, pid} = Akgentic.start_agent(CalculatorAgent, id: "calc-1")

# Blocking call — equivalent to Python's proxy_ask()
# Returns {:ok, agent} so we can inspect the result immediately.
{:ok, result_agent} = Akgentic.signal(pid, "add", %{a: 3.0, b: 7.0})
IO.puts("Blocking add(3, 7) result: #{result_agent.state.last_result}")

{:ok, result_agent} = Akgentic.signal(pid, "multiply", %{a: 6.0, b: 9.0})
IO.puts("Blocking multiply(6, 9) result: #{result_agent.state.last_result}")

IO.puts("\n=== OTP Path: Fire-and-Forget (signal_async/3) ===\n")

# Non-blocking cast — equivalent to Python's proxy_tell()
# Returns :ok immediately; the agent processes the signal asynchronously.
:ok = Akgentic.signal_async(pid, "add", %{a: 100.0, b: 200.0})
IO.puts("Fire-and-forget add(100, 200) dispatched — continuing immediately")

# Give the agent time to process the async signal
Process.sleep(200)

# Confirm result with a blocking call
{:ok, confirmed} = Akgentic.signal(pid, "add", %{a: 0.0, b: 0.0})
IO.puts("Previous async operation was: #{confirmed.state.last_operation}")

Akgentic.stop_agent(pid)
IO.puts("\n[Request/Response] Done!")
