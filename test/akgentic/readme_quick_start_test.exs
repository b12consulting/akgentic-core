defmodule Akgentic.Test.QuickStart.Actions.Echo do
  @moduledoc "Echoes a message by storing it in agent state."
  use Jido.Action,
    name: "qs_echo",
    description: "Echoes a message",
    schema: [
      content: [type: :string, required: true]
    ]

  def run(%{content: content}, _context) do
    {:ok, %{last_echo: content}}
  end
end

defmodule Akgentic.Test.QuickStart.EchoAgent do
  @moduledoc "EchoAgent used by the README quick-start tests."
  use Akgentic.Agent,
    name: "qs_echo_agent",
    description: "Echoes messages for quick-start tests",
    schema: [
      last_echo: [type: :string, default: ""]
    ],
    actions: [Akgentic.Test.QuickStart.Actions.Echo],
    signal_routes: [
      {"qs_echo", Akgentic.Test.QuickStart.Actions.Echo}
    ]
end

defmodule Akgentic.ReadmeQuickStartTest do
  @moduledoc """
  Validates the README quick-start pattern end-to-end.
  Port of tests/test_readme_quick_start.py from the Python akgentic codebase.
  """

  use ExUnit.Case, async: true

  alias Akgentic.Test.QuickStart.Actions.Echo
  alias Akgentic.Test.QuickStart.EchoAgent

  describe "pure functional path" do
    test "new/0 creates an agent with default state" do
      agent = EchoAgent.new()
      assert agent.state.last_echo == ""
    end

    test "cmd/2 with echo action updates state" do
      agent = EchoAgent.new()
      {agent, _directives} = EchoAgent.cmd(agent, {Echo, %{content: "Hello, World!"}})
      assert agent.state.last_echo == "Hello, World!"
    end

    test "multiple cmd/2 calls accumulate state changes" do
      agent = EchoAgent.new()

      {agent, _} = EchoAgent.cmd(agent, {Echo, %{content: "first"}})
      assert agent.state.last_echo == "first"

      {agent, _} = EchoAgent.cmd(agent, {Echo, %{content: "second"}})
      assert agent.state.last_echo == "second"
    end

    test "new/1 accepts an id option" do
      agent = EchoAgent.new(id: "my-echo-agent")
      assert agent.id == "my-echo-agent"
    end
  end

  describe "OTP path" do
    test "start_agent/2 starts a supervised agent process" do
      id = "qs-echo-#{System.unique_integer([:positive])}"
      {:ok, pid} = Akgentic.start_agent(EchoAgent, id: id)

      assert is_pid(pid)
      assert Process.alive?(pid)

      Akgentic.stop_agent(pid)
    end

    test "signal/3 sends a signal and returns updated agent" do
      id = "qs-signal-#{System.unique_integer([:positive])}"
      {:ok, pid} = Akgentic.start_agent(EchoAgent, id: id)

      {:ok, agent} = Akgentic.signal(pid, "qs_echo", %{content: "Hello, OTP!"})
      assert agent.state.last_echo == "Hello, OTP!"

      Akgentic.stop_agent(pid)
    end

    test "multiple signal/3 calls update state sequentially" do
      id = "qs-multi-signal-#{System.unique_integer([:positive])}"
      {:ok, pid} = Akgentic.start_agent(EchoAgent, id: id)

      {:ok, agent} = Akgentic.signal(pid, "qs_echo", %{content: "one"})
      assert agent.state.last_echo == "one"

      {:ok, agent} = Akgentic.signal(pid, "qs_echo", %{content: "two"})
      assert agent.state.last_echo == "two"

      Akgentic.stop_agent(pid)
    end

    test "signal_async/3 sends fire-and-forget signal and returns :ok" do
      id = "qs-async-#{System.unique_integer([:positive])}"
      {:ok, pid} = Akgentic.start_agent(EchoAgent, id: id)

      result = Akgentic.signal_async(pid, "qs_echo", %{content: "async message"})
      assert result == :ok

      # Wait for async cast to be processed, then verify with a sync signal
      Process.sleep(50)
      {:ok, agent} = Akgentic.signal(pid, "qs_echo", %{content: "sync confirmation"})
      assert agent.state.last_echo == "sync confirmation"

      Akgentic.stop_agent(pid)
    end

    test "stop_agent/1 terminates the agent process" do
      id = "qs-stop-#{System.unique_integer([:positive])}"
      {:ok, pid} = Akgentic.start_agent(EchoAgent, id: id)

      assert Process.alive?(pid)
      Akgentic.stop_agent(pid)

      # Give the process time to stop
      Process.sleep(50)
      refute Process.alive?(pid)
    end
  end
end
